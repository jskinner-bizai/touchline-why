"use strict";
(() => {
  const form = document.getElementById("access-form");
  const input = document.getElementById("access-code");
  const button = document.getElementById("access-submit");
  const status = document.getElementById("access-status");
  const session = document.getElementById("existing-session");
  function message(text, error = false) {
    status.textContent = text;
    status.classList.toggle("error", error);
  }
  async function request(path, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    try { return await fetch(path, { credentials: "same-origin", cache: "no-store", ...options, signal: controller.signal }); }
    finally { clearTimeout(timer); }
  }
  request("/api/session").then(async response => {
    if (!response.ok) return;
    const data = await response.json();
    if (data.authenticated === true) { session.hidden = false; form.hidden = true; }
  }).catch(() => {});
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const code = input.value.trim();
    if (!/^[A-Za-z0-9_-]{32,128}$/.test(code)) {
      message("Enter the access code shared by the playtest owner.", true); input.focus(); return;
    }
    button.disabled = true; input.disabled = true;
    message("Opening your private replay…");
    try {
      const response = await request("/api/access", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code }) });
      if (!response.ok) {
        if (response.status === 429) throw new Error("Too many access attempts. Wait a few minutes before trying again.");
        if ([400, 401, 403].includes(response.status)) throw new Error("That access code was not accepted or has expired. Check the code from the playtest owner.");
        throw new Error("The playtest is temporarily unavailable. Please try again later.");
      }
      form.reset();
      window.location.assign("/playtest");
    } catch (error) {
      message(error.name === "AbortError" ? "The service took too long to respond. Please try again shortly." : error.message, true);
      button.disabled = false; input.disabled = false;
    }
  });
})();
