const STORAGE_KEY = "predavanja";

function loadPredavanja() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || [];
  } catch {
    return [];
  }
}

function savePredavanja(list) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
}

function render() {
  const list = loadPredavanja();
  const ul = document.getElementById("predavanjaList");
  const empty = document.getElementById("menuEmpty");

  // Remove only dynamic (non-static) items, keep hardcoded ones.
  ul.querySelectorAll(":scope > li:not([data-static])").forEach(li => li.remove());

  const hasStatic = ul.querySelector(":scope > li[data-static]") !== null;
  empty.style.display = list.length === 0 && !hasStatic ? "block" : "none";

  list.forEach((p, idx) => {
    const li = document.createElement("li");
    li.className = "menu-item";

    const link = document.createElement("a");
    link.className = "menu-item-link";
    link.href = `index.html?name=${encodeURIComponent(p.name)}`;
    link.textContent = p.name;

    const del = document.createElement("button");
    del.className = "menu-item-del";
    del.type = "button";
    del.textContent = "×";
    del.title = "Delete";
    del.addEventListener("click", () => {
      const current = loadPredavanja();
      current.splice(idx, 1);
      savePredavanja(current);
      render();
    });

    li.appendChild(link);
    li.appendChild(del);
    ul.appendChild(li);
  });
}

document.getElementById("addForm").addEventListener("submit", e => {
  e.preventDefault();
  const input = document.getElementById("predavanjeName");
  const name = input.value.trim();
  if (!name) return;

  const list = loadPredavanja();
  list.push({ name, createdAt: Date.now() });
  savePredavanja(list);
  input.value = "";
  render();
});

render();
