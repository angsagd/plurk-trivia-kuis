// Penghitung karakter: <textarea data-hitung="id-elemen" data-batas="360">
document.addEventListener("input", function (e) {
  var t = e.target;
  if (!t.dataset || !t.dataset.hitung) return;
  var el = document.getElementById(t.dataset.hitung);
  if (!el) return;
  var n = t.value.length, batas = parseInt(t.dataset.batas || "360", 10);
  el.textContent = n + " / " + batas + " karakter";
  el.style.color = n > batas ? "#B91C1C" : "";
});
// Konfirmasi untuk tombol berbahaya: <button data-yakin="Pesan?">
document.addEventListener("submit", function (e) {
  var b = e.submitter;
  if (b && b.dataset && b.dataset.yakin && !window.confirm(b.dataset.yakin)) e.preventDefault();
});
