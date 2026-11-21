const dialog = document.querySelector("#proofDialog");
const media = document.querySelector("#proofMedia");
let serial = 0,
  objectURL = null,
  task = null,
  rendering = null;
function release() {
  serial++;
  if (rendering) rendering.cancel();
  rendering = null;
  if (task) task.destroy().catch(() => {});
  task = null;
  if (objectURL) URL.revokeObjectURL(objectURL);
  objectURL = null;
  media.replaceChildren();
}
dialog.addEventListener("close", release);
export async function viewProof(blob) {
  release();
  const version = serial;
  if (!dialog.open) dialog.showModal();
  const loading = document.createElement("p");
  loading.setAttribute("role", "status");
  loading.textContent = "Abriendo comprobante…";
  media.replaceChildren(loading);
  if (["image/jpeg", "image/png", "image/webp"].includes(blob.type)) {
    const img = document.createElement("img");
    objectURL = URL.createObjectURL(blob);
    img.alt = "Comprobante de pago";
    img.onerror = () => {
      if (serial === version) media.textContent = "La imagen no se pudo leer.";
    };
    img.src = objectURL;
    const zoom = document.createElement("button");
    zoom.type = "button";
    zoom.textContent = "Ampliar imagen";
    zoom.onclick = () => {
      img.classList.toggle("enlarged");
      zoom.textContent = img.classList.contains("enlarged")
        ? "Ajustar imagen"
        : "Ampliar imagen";
    };
    media.replaceChildren(zoom, img);
    return;
  }
  if (blob.type !== "application/pdf") {
    loading.textContent = "Formato sin vista previa.";
    return;
  }
  try {
    const pdfjs = await import("./vendor/pdfjs/build/pdf.min.mjs");
    const data = new Uint8Array(await blob.arrayBuffer());
    if (version !== serial) return;
    const base = new URL("./vendor/pdfjs/", import.meta.url);
    pdfjs.GlobalWorkerOptions.workerSrc = new URL(
      "build/pdf.worker.min.mjs",
      base,
    ).href;
    task = pdfjs.getDocument({
      data,
      isEvalSupported: false,
      enableXfa: false,
      wasmUrl: new URL("wasm/", base).href,
      iccUrl: new URL("iccs/", base).href,
      standardFontDataUrl: new URL("standard_fonts/", base).href,
      cMapUrl: new URL("cmaps/", base).href,
      cMapPacked: true,
    });
    const pdf = await task.promise;
    if (version !== serial) return;
    const bar = document.createElement("div");
    bar.className = "actions";
    const prev = document.createElement("button"),
      next = document.createElement("button"),
      status = document.createElement("span"),
      canvas = document.createElement("canvas");
    prev.textContent = "Página anterior";
    next.textContent = "Página siguiente";
    status.setAttribute("role", "status");
    canvas.setAttribute("role", "img");
    bar.append(prev, status, next);
    media.replaceChildren(bar, canvas);
    let page = 1;
    async function draw(number) {
      prev.disabled = next.disabled = true;
      page = number;
      try {
        const p = await pdf.getPage(page);
        if (version !== serial) return;
        const unit = p.getViewport({ scale: 1 });
        const scale = Math.min(
          2400 / unit.width,
          3000 / unit.height,
          Math.max(
            1,
            (Math.min(2, devicePixelRatio) * (media.clientWidth - 8)) /
              unit.width,
          ),
        );
        const viewport = p.getViewport({ scale });
        canvas.width = Math.ceil(viewport.width);
        canvas.height = Math.ceil(viewport.height);
        rendering = p.render({
          canvas,
          canvasContext: canvas.getContext("2d"),
          viewport,
        });
        await rendering.promise;
        if (version !== serial) return;
        status.textContent = "Página " + page + " de " + pdf.numPages;
        canvas.setAttribute(
          "aria-label",
          "Comprobante · " + status.textContent,
        );
        prev.disabled = page === 1;
        next.disabled = page === pdf.numPages;
      } catch {
        if (version === serial)
          status.textContent = "No se pudo mostrar esta página.";
      }
    }
    prev.onclick = () => draw(page - 1);
    next.onclick = () => draw(page + 1);
    await draw(1);
  } catch {
    if (version === serial)
      media.textContent =
        "No se pudo abrir el PDF. Comprueba que el archivo sea legible y no requiera contraseña.";
  }
}
