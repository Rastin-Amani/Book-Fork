// Book Fork client bootstrap.
// Responsibilities: inject the CSRF header into HTMX requests and surface
// HTMX error responses as toasts. No application logic belongs here.

document.body.addEventListener("htmx:configRequest", (event) => {
  const meta = document.querySelector('meta[name="csrf-token"]');
  if (meta && meta.content) {
    event.detail.headers["X-CSRF-Token"] = meta.content;
  }
});

document.body.addEventListener("htmx:responseError", (event) => {
  const status = event.detail.xhr.status;
  // Dispatch on window: the toast listens via @show-toast.window, and a
  // non-bubbling custom event on body would never reach it.
  window.dispatchEvent(
    new CustomEvent("show-toast", {
      detail: { message: `Request failed (${status}).`, type: "error" },
    })
  );
});
