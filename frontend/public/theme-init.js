/* global document, localStorage, matchMedia */
(() => {
  const saved = localStorage.getItem("fk-theme-preference") || "system";
  const dark =
    saved === "dark" ||
    (saved === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  document.documentElement.style.colorScheme = dark ? "dark" : "light";
})();
