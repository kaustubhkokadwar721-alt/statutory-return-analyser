"use strict";
// Theme switcher — swaps the skin stylesheet, persists choice. Content/markup unchanged.
(function () {
  var KEY = "gstr-theme";
  var DEFAULT = "swiss";
  var sel = document.getElementById("themeSelect");
  var skin = document.getElementById("themeSkin");
  var saved = localStorage.getItem(KEY) || DEFAULT;

  function apply(name) {
    skin.href = "themes/" + name + ".css";
    document.documentElement.setAttribute("data-theme", name);
    localStorage.setItem(KEY, name);
    if (sel.value !== name) sel.value = name;
  }

  if (sel) {
    sel.value = saved;
    apply(saved);
    sel.addEventListener("change", function () { apply(sel.value); });
  }
})();
