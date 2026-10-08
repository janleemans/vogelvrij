(() => {
  "use strict";

  const cards = [...document.querySelectorAll(".article-card")];

  function updateOverflow(card) {
    if (card.classList.contains("article-card-expanded")) return;
    const body = card.querySelector(".article-body");
    const button = card.querySelector(".article-expand");
    const overflows = body.scrollHeight > body.clientHeight + 1;
    button.hidden = !overflows;
    card.classList.toggle("article-card-overflowing", overflows);
  }

  cards.forEach((card) => {
    const button = card.querySelector(".article-expand");
    const label = card.querySelector(".article-expand-label");
    button.addEventListener("click", () => {
      const expanded = card.classList.toggle("article-card-expanded");
      card.classList.toggle("article-card-overflowing", !expanded);
      button.setAttribute("aria-expanded", String(expanded));
      label.textContent = expanded ? "Artikel inklappen" : "Toon volledig artikel";
      if (!expanded) {
        card.scrollIntoView({ behavior: "smooth", block: "start" });
        requestAnimationFrame(() => updateOverflow(card));
      }
    });
    updateOverflow(card);
  });

  window.addEventListener("resize", () => cards.forEach(updateOverflow));
})();
