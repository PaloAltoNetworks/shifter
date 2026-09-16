(function () {
  "use strict";

  var status = document.getElementById("invitation-status");
  var exchange = document.getElementById("invitation-exchange");
  var params = new URLSearchParams(globalThis.location.hash.slice(1));
  var token = params.get("token") || "";
  globalThis.history.replaceState(null, "", globalThis.location.pathname + globalThis.location.search);

  function fail() {
    status.textContent = "This invitation could not be accepted. Ask a workspace administrator for a new invitation.";
  }

  function navigate(url) {
    var link = document.createElement("a");
    link.href = url;
    link.hidden = true;
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  if (!exchange || !token || token.length > 4096) {
    fail();
    return;
  }
  var csrf = document.cookie
    .split(";")
    .map(function (part) { return part.trim(); })
    .find(function (part) { return part.startsWith("csrftoken="); });
  if (!csrf) {
    fail();
    return;
  }
  fetch(exchange.dataset.stageUrl, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRFToken": decodeURIComponent(csrf.slice(10)) },
    body: JSON.stringify({ token: token })
  }).then(function (response) {
    if (!response.ok) throw new Error("exchange_failed");
    return response.json();
  }).then(function (body) {
    navigate(body.redirect_url);
  }).catch(fail);
}());
