document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy-target]");
  if (!button) return;

  const value = document.getElementById(button.dataset.copyTarget);
  if (!value) return;

  const status = button.closest(".copy-block")?.querySelector(".copy-status");
  try {
    await navigator.clipboard.writeText(value.textContent.trim());
    if (status) status.textContent = "Copied";
  } catch {
    const range = document.createRange();
    range.selectNodeContents(value);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    if (status) status.textContent = "Select and copy the highlighted text";
  }
});
