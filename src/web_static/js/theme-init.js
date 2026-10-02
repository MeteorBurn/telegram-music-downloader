// Runs before first paint (classic, blocking) so the stored theme never flashes.
(function () {
  var theme = "dark";
  try {
    var stored = localStorage.getItem("tmd-theme");
    if (stored === "light" || stored === "dark") theme = stored;
  } catch (error) {
    // Storage can be unavailable (private mode); the dark default stands.
  }
  document.documentElement.dataset.theme = theme;
})();
