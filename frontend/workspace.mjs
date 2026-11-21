// The compact menu is a rail on desktop and a disclosure on narrow screens.
export function createWorkspace() {
  const narrow = matchMedia("(max-width: 920px)");
  const admin = document.querySelector("#admin");
  const menu = document.querySelector("#navToggle");
  const list = document.querySelector("#directoryToggle");
  const directoryBar = document.querySelector(".directoryBar"), header = document.querySelector(".chatHeader");
  let compactMenu = false, compactList = false, mobileMenu = false, mobileList = false;
  function control(button, expanded, name, caption) {
    button.setAttribute("aria-expanded", String(expanded));
    button.setAttribute("aria-label", name);
    button.title = name;
    button.querySelector("span").textContent = caption;
  }
  function render() {
    const hadListFocus = document.activeElement === list;
    const chat = admin.classList.contains("chatOpen");
    const menuExpanded = narrow.matches ? mobileMenu : !compactMenu;
    const listExpanded = narrow.matches ? !chat || mobileList : !compactList;
    document.body.classList.toggle("navOpen", narrow.matches && mobileMenu);
    document.body.classList.toggle("compactMenu", !narrow.matches && compactMenu);
    admin.classList.toggle("compactDirectory", !narrow.matches && compactList);
    admin.classList.toggle("browsingDirectory", narrow.matches && chat && mobileList);
    const menuAction = menuExpanded ? "Contraer menú" : "Expandir menú";
    control(menu, menuExpanded, menuAction + " principal", menuAction);
    if (narrow.matches) {
      const destination = listExpanded ? "Volver al chat" : "Volver a la lista";
      control(list, listExpanded, destination, destination);
    } else {
      const action = listExpanded ? "Contraer lista" : "Expandir lista";
      control(list, listExpanded, action + " de conversaciones", action);
    }
    const host = narrow.matches && chat && !listExpanded ? header : directoryBar;
    if (list.parentElement !== host) {
      host.append(list);
      if (hadListFocus) list.focus({preventScroll: true});
    }
    list.hidden = narrow.matches && !chat;
  }
  menu.onclick = () => {
    if (narrow.matches) mobileMenu = !mobileMenu;
    else compactMenu = !compactMenu;
    render();
  };
  list.onclick = () => {
    if (narrow.matches) mobileList = !mobileList;
    else compactList = !compactList;
    render();
  };
  narrow.addEventListener("change", render);
  render();
  return {
    render,
    showChat() { mobileList = false; render(); },
    showList() { mobileList = false; compactList = false; render(); },
    closeMenu() { mobileMenu = false; render(); },
  };
}
