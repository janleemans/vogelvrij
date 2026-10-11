(() => {
  "use strict";

  const cards = [...document.querySelectorAll(".article-card")];

  function setExpanded(card, expanded) {
    const button = card.querySelector(".article-expand");
    const label = card.querySelector(".article-expand-label");
    card.classList.toggle("article-card-expanded", expanded);
    card.classList.toggle("article-card-overflowing", !expanded);
    button.hidden = false;
    button.setAttribute("aria-expanded", String(expanded));
    label.textContent = expanded ? "Artikel inklappen" : "Toon volledig artikel";
  }

  function scrollToArticle(card, behavior) {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => card.scrollIntoView({ behavior, block: "start" }));
    });
  }

  function cardFromHash() {
    if (!window.location.hash) return null;
    try {
      const card = document.getElementById(decodeURIComponent(window.location.hash.slice(1)));
      return card && card.classList.contains("article-card") ? card : null;
    } catch (_error) {
      return null;
    }
  }

  function openHashArticle() {
    const card = cardFromHash();
    if (!card) return;
    setExpanded(card, true);
    scrollToArticle(card, "auto");
  }

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
    button.addEventListener("click", () => {
      const expanded = !card.classList.contains("article-card-expanded");
      setExpanded(card, expanded);
      if (expanded) {
        window.history.replaceState(null, "", `#${encodeURIComponent(card.id)}`);
        scrollToArticle(card, "smooth");
      } else {
        if (cardFromHash() === card) {
          window.history.replaceState(
            null, "", `${window.location.pathname}${window.location.search}`
          );
        }
        scrollToArticle(card, "smooth");
        requestAnimationFrame(() => updateOverflow(card));
      }
    });
    updateOverflow(card);
  });

  window.addEventListener("resize", () => cards.forEach(updateOverflow));
  window.addEventListener("hashchange", openHashArticle);
  openHashArticle();
})();
