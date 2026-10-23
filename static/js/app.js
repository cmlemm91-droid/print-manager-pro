/* PrintManager Pro – Interaktionen ohne externe Bibliotheken. */
(function () {
  "use strict";

  var euro = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" });
  var number = new Intl.NumberFormat("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  function toNumber(value) {
    if (value === null || value === undefined) return 0;
    var parsed = parseFloat(String(value).replace(/\s/g, "").replace(",", "."));
    return isFinite(parsed) ? parsed : 0;
  }

  function setupSidebar() {
    var sidebar = document.getElementById("sidebar");
    var backdrop = document.getElementById("sidebar-backdrop");
    if (!sidebar) return;

    function close() {
      sidebar.classList.remove("open");
      if (backdrop) backdrop.classList.remove("show");
    }

    document.querySelectorAll("[data-toggle-sidebar]").forEach(function (button) {
      button.addEventListener("click", function () {
        sidebar.classList.toggle("open");
        if (backdrop) backdrop.classList.toggle("show", sidebar.classList.contains("open"));
      });
    });
    if (backdrop) backdrop.addEventListener("click", close);
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") close();
    });
  }

  function setupConfirmations() {
    document.querySelectorAll("form[data-confirm]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        if (!window.confirm(form.getAttribute("data-confirm"))) {
          event.preventDefault();
        }
      });
    });
  }

  function setupFlash() {
    var flash = document.querySelector(".flash");
    if (flash) {
      window.setTimeout(function () {
        flash.classList.add("flash-hide");
        window.setTimeout(function () { flash.remove(); }, 400);
      }, 4500);
    }
  }

  function setupAutosubmit() {
    document.querySelectorAll("[data-autosubmit]").forEach(function (element) {
      element.addEventListener("change", function () {
        var form = element.closest("form");
        if (form) form.submit();
      });
    });
  }

  function setupCalculator() {
    var form = document.getElementById("order-form");
    var dataTag = document.getElementById("calc-data");
    if (!form || !dataTag) return;

    var data;
    try {
      data = JSON.parse(dataTag.textContent);
    } catch (error) {
      return;
    }

    var settings = data.settings || {};
    var priceField = form.elements["price"];
    var overrideField = form.elements["price_override"];

    function field(name) {
      return form.elements[name] || null;
    }

    function value(name) {
      var element = field(name);
      return element ? toNumber(element.value) : 0;
    }

    function setText(id, text) {
      var element = document.getElementById(id);
      if (element) element.textContent = text;
    }

    function setHidden(id, visible) {
      var element = document.getElementById(id);
      if (element) element.style.display = visible ? "" : "none";
    }

    function recalculate() {
      var materialElement = field("material_id");
      var printerElement = field("printer_id");
      var materialPrice = data.materials[materialElement ? materialElement.value : ""] || 0;
      var printer = data.printers[printerElement ? printerElement.value : ""] || { cost: 0, power: 150 };

      var weight = Math.max(0, value("weight_used"));
      var duration = Math.max(0, value("duration_hours"));
      var cadHours = Math.max(0, value("cad_hours"));
      var extra = Math.max(0, value("extra_cost"));
      var margin = value("margin_percent");

      var materialCost = (weight / 1000) * materialPrice;
      var machineCost = duration * printer.cost;
      var cadCost = cadHours * (settings.cad || 0);
      var energyCost = duration * ((printer.power || 150) / 1000) * (settings.electricity || 0);
      var costTotal = materialCost + machineCost + cadCost + energyCost + extra;

      var override = overrideField ? overrideField.checked : false;
      var price = override ? Math.max(0, value("price")) : costTotal * (1 + margin / 100);
      if (!override && priceField) {
        priceField.value = price ? price.toFixed(2) : "";
      }

      var profit = price - costTotal;
      var effective = price > 0 ? (profit / price) * 100 : 0;
      var vat = settings.small_business ? 0 : price * ((settings.vat || 0) / 100);
      var gross = price + vat;

      setText("calc-material", euro.format(materialCost));
      setText("calc-machine", euro.format(machineCost));
      setText("calc-cad", euro.format(cadCost));
      setText("calc-energy", euro.format(energyCost));
      setText("calc-extra", euro.format(extra));
      setText("calc-cost", euro.format(costTotal));
      setText("calc-price", euro.format(price));
      setText("calc-profit", euro.format(profit));
      setText("calc-margin", number.format(effective) + " %");
      setText("calc-vat", euro.format(vat));
      setText("calc-gross", euro.format(gross));
      setText("calc-vat-label", settings.small_business ? "Kleinunternehmer" : "USt. " + (settings.vat || 0) + " %");
      setHidden("calc-vat-row", !settings.small_business);
      setHidden("calc-margin-negative", profit >= 0);
      setHidden("calc-margin-positive", profit < 0);

      if (priceField) {
        priceField.readOnly = !override;
        priceField.classList.toggle("manual", override);
      }
    }

    if (overrideField && priceField) {
      overrideField.addEventListener("change", function () {
        priceField.readOnly = !overrideField.checked;
        if (overrideField.checked) {
          priceField.focus();
          priceField.select();
        }
        recalculate();
      });
    }

    form.querySelectorAll("input, select").forEach(function (element) {
      element.addEventListener("input", recalculate);
      element.addEventListener("change", recalculate);
    });

    recalculate();
  }

  document.addEventListener("DOMContentLoaded", function () {
    setupSidebar();
    setupConfirmations();
    setupFlash();
    setupAutosubmit();
    setupCalculator();
  });
})();
