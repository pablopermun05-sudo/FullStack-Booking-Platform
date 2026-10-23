
(() => {
    "use strict";

    document.addEventListener("DOMContentLoaded", () => {
        const residenceSelect = document.getElementById(
            "guest-residence-country"
        );

        if (!residenceSelect) return;

        if (typeof window.Choices !== "function") {
            console.error("No se ha podido cargar Choices.js.");
            return;
        }

        const countries = [
            ["ES", "España"],
            ["AR", "Argentina"],
            ["BO", "Bolivia"],
            ["BR", "Brasil"],
            ["CA", "Canadá"],
            ["CL", "Chile"],
            ["CN", "China"],
            ["CO", "Colombia"],
            ["CR", "Costa Rica"],
            ["CU", "Cuba"],
            ["DO", "República Dominicana"],
            ["EC", "Ecuador"],
            ["SV", "El Salvador"],
            ["US", "Estados Unidos"],
            ["PH", "Filipinas"],
            ["FR", "Francia"],
            ["GT", "Guatemala"],
            ["HN", "Honduras"],
            ["IN", "India"],
            ["IT", "Italia"],
            ["JP", "Japón"],
            ["MX", "México"],
            ["NI", "Nicaragua"],
            ["PA", "Panamá"],
            ["PY", "Paraguay"],
            ["PE", "Perú"],
            ["PT", "Portugal"],
            ["GB", "Reino Unido"],
            ["DE", "Alemania"],
            ["UY", "Uruguay"],
            ["VE", "Venezuela"],
            ["BE", "Bélgica"],
            ["CH", "Suiza"],
            ["NL", "Países Bajos"],
            ["IE", "Irlanda"],
            ["AT", "Austria"],
            ["AU", "Australia"],
            ["SE", "Suecia"],
            ["NO", "Noruega"],
            ["DK", "Dinamarca"],
            ["FI", "Finlandia"],
            ["PL", "Polonia"],
            ["GR", "Grecia"],
            ["MA", "Marruecos"],
            ["DZ", "Argelia"],
            ["TN", "Túnez"],
            ["TR", "Turquía"],
            ["UA", "Ucrania"],
            ["RU", "Rusia"],
            ["KR", "Corea del Sur"],
            ["TH", "Tailandia"],
            ["ID", "Indonesia"],
            ["NZ", "Nueva Zelanda"],
            ["ZA", "Sudáfrica"]
        ];

        const existingCodes = new Set(
            Array.from(residenceSelect.options, option => option.value)
        );

        countries.forEach(([code, name]) => {
            if (!existingCodes.has(code)) {
                residenceSelect.add(new Option(name, code));
            }
        });

        new Choices(residenceSelect, {
            searchEnabled: true,
            searchPlaceholderValue: "Buscar país...",
            itemSelectText: "",
            shouldSort: false,
            allowHTML: true,
            searchResultLimit: 250,
            noResultsText: "No se encontraron países",
            noChoicesText: "No hay países disponibles",

            callbackOnCreateTemplates: function (template) {
                function countryMarkup(data) {
                    const code = String(data.value || "").toLowerCase();

                    return template(`
                        <span class="b-residence-option">
                            <span
                                class="fi fi-${code} b-residence-flag"
                                aria-hidden="true"
                            ></span>
                            <span>${data.label}</span>
                        </span>
                    `);
                }

                return {
                    item: function (classNames, data) {
                        return template(`
                            <div
                                class="${classNames.item} ${classNames.itemSelectable}"
                                data-item
                                data-id="${data.id}"
                                data-value="${data.value}"
                                aria-selected="true"
                            >
                                ${countryMarkup(data).outerHTML}
                            </div>
                        `);
                    },

                    choice: function (classNames, data) {
                        return template(`
                            <div
                                class="${classNames.item} ${classNames.itemChoice}"
                                data-choice
                                data-id="${data.id}"
                                data-value="${data.value}"
                                role="option"
                            >
                                ${countryMarkup(data).outerHTML}
                            </div>
                        `);
                    }
                };
            }
        });
    });
})();