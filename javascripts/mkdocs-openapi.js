(function () {
  "use strict";

  function copyText(value) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(value);
    }
    var input = document.createElement("textarea");
    input.value = value;
    input.setAttribute("readonly", "");
    input.style.position = "fixed";
    input.style.opacity = "0";
    document.body.appendChild(input);
    input.select();
    document.execCommand("copy");
    input.remove();
    return Promise.resolve();
  }

  function showFeedback(container, message) {
    var feedback = container.querySelector(
      ".api-copy-feedback, .api-page-actions__feedback"
    );
    if (!feedback) return;
    feedback.textContent = message;
    window.setTimeout(function () {
      feedback.textContent = "";
    }, 1800);
  }

  function pageMarkdown(container) {
    var source = container.querySelector("[data-api-page-markdown]");
    if (!source) return "";
    try {
      return JSON.parse(source.textContent || '""');
    } catch (_error) {
      return "";
    }
  }

  function openInAI(provider) {
    var prompt =
      "Read this documentation page and answer questions about it: " +
      window.location.href;
    var baseUrl =
      provider === "claude"
        ? "https://claude.ai/new?q="
        : "https://chatgpt.com/?q=";
    window.open(baseUrl + encodeURIComponent(prompt), "_blank", "noopener,noreferrer");
  }

  function closePageActions(container) {
    var details = container.querySelector("details");
    if (details) details.open = false;
  }

  function createEndpointBars(root) {
    root.querySelectorAll("[data-api-endpoint]").forEach(function (source) {
      if (source.dataset.apiReady) return;
      source.dataset.apiReady = "true";

      var operation;
      try {
        operation = JSON.parse(source.textContent || "{}");
      } catch (_error) {
        return;
      }
      if (!operation.method || !operation.endpoint) return;

      var article = source.closest("article");
      var heading = article && article.querySelector("h1");
      if (!article || !heading || article.querySelector(".api-endpoint")) return;

      var bar = document.createElement("div");
      bar.className = "api-endpoint";

      var method = document.createElement("span");
      method.className =
        "api-endpoint__method http-method " + operation.method.toLowerCase();
      method.textContent = operation.method === "DELETE" ? "DEL" : operation.method;
      bar.appendChild(method);

      var endpoint = document.createElement("code");
      endpoint.className = "api-endpoint__url";
      endpoint.textContent = operation.endpoint;
      bar.appendChild(endpoint);

      var button = document.createElement("button");
      button.className = "api-copy-button";
      button.type = "button";
      button.dataset.apiCopyEndpoint = "";
      button.setAttribute("aria-label", "Copy endpoint URL");
      button.title = "Copy endpoint URL";
      button.innerHTML =
        '<svg viewBox="0 0 24 24" aria-hidden="true">' +
        '<path d="M8 7V5a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 ' +
        '2h-2v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h3Zm2 0h5a2 ' +
        '2 0 0 1 2 2v5h2V5h-9v2Zm5 2H5v10h10V9Z"/></svg>';
      bar.appendChild(button);

      var feedback = document.createElement("span");
      feedback.className = "api-copy-feedback";
      feedback.setAttribute("aria-live", "polite");
      bar.appendChild(feedback);

      heading.insertAdjacentElement("afterend", bar);
    });
  }

  function initialize(root) {
    createEndpointBars(root);

    root.querySelectorAll("[data-api-copy-endpoint]").forEach(function (button) {
      if (button.dataset.apiReady) return;
      button.dataset.apiReady = "true";
      button.addEventListener("click", function () {
        var container = button.closest(".api-endpoint");
        var endpoint = container && container.querySelector(".api-endpoint__url");
        if (!container || !endpoint) return;
        copyText(endpoint.textContent || "").then(function () {
          button.classList.add("is-copied");
          showFeedback(container, "Copied");
          window.setTimeout(function () {
            button.classList.remove("is-copied");
          }, 1800);
        });
      });
    });

    root.querySelectorAll(".api-page-actions").forEach(function (container) {
      if (container.dataset.apiReady) return;
      container.dataset.apiReady = "true";
      var copyButtons = container.querySelectorAll("[data-api-copy-page]");
      var viewButton = container.querySelector("[data-api-view-markdown]");
      var aiButtons = container.querySelectorAll("[data-api-open-ai]");

      copyButtons.forEach(function (copyButton) {
        copyButton.addEventListener("click", function () {
          copyText(pageMarkdown(container)).then(function () {
            showFeedback(container, "Markdown copied");
            closePageActions(container);
          });
        });
      });

      if (viewButton) {
        viewButton.addEventListener("click", function () {
          var blob = new Blob([pageMarkdown(container)], {
            type: "text/plain;charset=utf-8",
          });
          var url = URL.createObjectURL(blob);
          window.open(url, "_blank", "noopener");
          window.setTimeout(function () {
            URL.revokeObjectURL(url);
          }, 60000);
          closePageActions(container);
        });
      }

      aiButtons.forEach(function (button) {
        button.addEventListener("click", function () {
          openInAI(button.dataset.apiOpenAi);
          closePageActions(container);
        });
      });
    });
  }

  function start() {
    initialize(document);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }

  if (typeof document$ !== "undefined") {
    document$.subscribe(start);
  }
})();
