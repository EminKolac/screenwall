// Applies an explicit light/dark choice before first paint to avoid a theme flash.
(function () {
  try {
    var value = window.localStorage.getItem("screenwall.theme");
    if (value === "light" || value === "dark") document.documentElement.setAttribute("data-theme", value);
  } catch (error) {
    /* storage unavailable: fall back to the system theme */
  }
})();
