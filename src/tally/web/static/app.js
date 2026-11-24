(function () {
  "use strict";
  var raw = document.getElementById("chart-data");
  var data = raw ? JSON.parse(raw.textContent) : null;

  document.querySelectorAll(".dot[data-color]").forEach(function (el) {
    el.style.background = el.getAttribute("data-color");
  });
  document.querySelectorAll("select[data-autosubmit]").forEach(function (el) {
    el.addEventListener("change", function () { el.form.submit(); });
  });

  if (!data || typeof Chart === "undefined") return;
  var dollars = function (cents) { return cents / 100; };
  var fmt = function (v) { return "$" + Number(v).toFixed(2); };

  var donut = document.getElementById("cat-chart");
  if (donut && data.cats.length) {
    new Chart(donut, {
      type: "doughnut",
      data: {
        labels: data.cats.map(function (c) { return c.label; }),
        datasets: [{
          data: data.cats.map(function (c) { return dollars(c.cents); }),
          backgroundColor: data.cats.map(function (c) { return c.color; }),
          borderWidth: 0
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: "55%",
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: function (ctx) { return ctx.label + " " + fmt(ctx.parsed); } } }
        },
        onClick: function (_evt, els) {
          if (!els.length) return;
          var params = new URLSearchParams(window.location.search);
          params.set("category", data.cats[els[0].index].slug);
          window.location.search = params.toString();
        }
      }
    });
  }

  var bars = document.getElementById("bucket-chart");
  if (bars) {
    new Chart(bars, {
      type: "bar",
      data: {
        labels: data.buckets.map(function (b) { return b.label; }),
        datasets: [{
          data: data.buckets.map(function (b) { return dollars(b.cents); }),
          backgroundColor: "#3b82f6"
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: function (ctx) { return fmt(ctx.parsed.y); } } }
        },
        scales: { y: { beginAtZero: true, ticks: { callback: function (v) { return "$" + v; } } } }
      }
    });
  }
})();
