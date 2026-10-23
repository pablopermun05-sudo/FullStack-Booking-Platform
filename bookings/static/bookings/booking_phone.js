
(() => {
    "use strict";

    document.addEventListener("DOMContentLoaded", () => {
        const form = document.getElementById("booking-details-form");
        const phoneInput = document.getElementById("guest-phone-local");
        const phoneHidden = document.getElementById("guest-phone");

        if (!form || !phoneInput || !phoneHidden) return;

        if (typeof window.intlTelInput !== "function") {
            console.error("No se ha podido cargar intl-tel-input.");
            return;
        }

        const iti = window.intlTelInput(phoneInput, {
            initialCountry: "es",
            countrySearch: true,
            countryNameLocale: "es",
            separateDialCode: true,
            countrySelectorMode: "AUTO",
            nationalMode: false,

            i18n: {
                searchPlaceholder: "Buscar país",
                noCountrySelected: "Ningún país seleccionado",
                countryListAriaLabel: "Lista de países",
                searchCountryAriaLabel: "Buscar país",
                clearSearchAriaLabel: "Borrar búsqueda"
            },

            loadUtils: () =>
                import(
                    "https://cdn.jsdelivr.net/npm/intl-tel-input@25/build/js/utils.js"
                )
        });

        function syncPhoneValue() {
            const rawPhone = phoneInput.value.trim();

            if (!rawPhone) {
                phoneHidden.value = "";
                return;
            }

            try {
                phoneHidden.value = iti.getNumber() || "";
            } catch (error) {
                phoneHidden.value = "";
            }
        }

        phoneInput.addEventListener("input", syncPhoneValue);
        phoneInput.addEventListener("countrychange", syncPhoneValue);

        // API compartida con booking_details.js.
        window.bookingPhone = {
            ready: iti.promise,
            sync: syncPhoneValue
        };

        syncPhoneValue();
    });
})();