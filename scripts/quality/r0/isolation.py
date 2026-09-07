"""V0 isolation narrowed to an attested R0 instance and one job-created database."""

from __future__ import annotations

import json
import os
import re
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import asyncpg

OUT = Path("/quality-output")


class Isolation:
    def __init__(self) -> None:
        self.nonce = os.environ["AUDIT_NONCE"]
        if not re.fullmatch(r"[a-f0-9]{32}", self.nonce):
            raise RuntimeError("Missing isolated resource nonce")
        self.container = os.environ["AUDIT_DB_CONTAINER"]
        self.system_identifier = os.environ["QUALITY_SYSTEM_IDENTIFIER"]
        self.role = "audit_" + self.nonce
        self.password = "synthetic_" + self.nonce
        self.ip = socket.gethostbyname("audit-postgres")
        self.database = "r0_" + os.environ["QUALITY_STAGE"] + "_test_" + self.nonce[:12]
        self.original_pg_connect = asyncpg.connect
        self.blocked: list[str] = []

    def url(self) -> str:
        return f"postgresql+asyncpg://{self.role}:{self.password}@{self.ip}:5432/{self.database}"

    def check_destination(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        fields = dict(kwargs)
        dsn = args[0] if args else fields.pop("dsn", None)
        if dsn:
            parsed = urlsplit(dsn)
            fields = dict(
                host=parsed.hostname,
                port=parsed.port or 5432,
                user=parsed.username,
                password=parsed.password,
                database=parsed.path.lstrip("/"),
                **fields,
            )
        expected = dict(host=self.ip, port=5432, user=self.role, password=self.password)
        for key, value in expected.items():
            if fields.get(key, 5432 if key == "port" else None) != value:
                raise RuntimeError("R0_UNAUTHORIZED_DATABASE_DESTINATION")
        if fields.get("database") not in {"postgres", self.database}:
            raise RuntimeError("R0_UNAUTHORIZED_DATABASE_DESTINATION")

    async def connect(self, *args: Any, **kwargs: Any) -> asyncpg.Connection:
        self.check_destination(args, kwargs)
        connection = await self.original_pg_connect(*args, **kwargs)
        try:
            row = await connection.fetchrow(
                "SELECT current_user AS role, current_database() AS db, "
                "current_setting('server_version_num')::int AS version, "
                "pg_get_userbyid(datdba) AS owner, "
                "(SELECT system_identifier::text FROM pg_control_system()) AS instance "
                "FROM pg_database WHERE datname=current_database()"
            )
            if (
                row["role"] != self.role
                or row["owner"] != self.role
                or row["instance"] != self.system_identifier
                or not 160000 <= row["version"] < 170000
            ):
                raise RuntimeError("R0_DATABASE_ATTESTATION_FAILED")
            with (OUT / "verified_connections.jsonl").open("a") as handle:
                handle.write(
                    json.dumps(
                        dict(row)
                        | {
                            "container": self.container,
                            "nonce": self.nonce,
                        }
                    )
                    + "\n"
                )
            return connection
        except BaseException:
            await connection.close()
            raise

    def install(self) -> None:
        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex
        original_dns = socket.getaddrinfo

        def allow(address: Any) -> None:
            if not isinstance(address, tuple) or address[0] not in {
                self.ip,
                "127.0.0.1",
                "::1",
            }:
                self.blocked.append("socket")
                raise RuntimeError("R0_EXTERNAL_NETWORK_BLOCKED")

        def connect(sock: socket.socket, address: Any) -> Any:
            allow(address)
            return original_connect(sock, address)

        def connect_ex(sock: socket.socket, address: Any) -> Any:
            allow(address)
            return original_connect_ex(sock, address)

        def dns(host: Any, *args: Any, **kwargs: Any) -> Any:
            if host not in {None, self.ip, "127.0.0.1", "::1", "localhost"}:
                self.blocked.append("dns")
                raise RuntimeError("R0_EXTERNAL_DNS_BLOCKED")
            return original_dns(host, *args, **kwargs)

        socket.socket.connect = connect
        socket.socket.connect_ex = connect_ex
        socket.getaddrinfo = dns
        asyncpg.connect = self.connect

    async def create_database(self) -> None:
        connection = await self.connect(
            host=self.ip, user=self.role, password=self.password, database="postgres"
        )
        try:
            if await connection.fetchval(
                "SELECT 1 FROM pg_database WHERE datname=$1", self.database
            ):
                raise RuntimeError("R0 refuses to reuse an existing database")
            await connection.execute(f'CREATE DATABASE "{self.database}" OWNER "{self.role}"')
        finally:
            await connection.close()
