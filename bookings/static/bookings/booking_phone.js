(() => {
    "use strict";

    document.addEventListener("DOMContentLoaded", () => {
        const form =
            document.getElementById("booking-details-form") ||
            document.getElementById("user-profile-form");

        const phoneInput = document.getElementById("guest-phone-local");
        const phoneHidden = document.getElementById("guest-phone");

        if (!form || !phoneInput || !phoneHidden) return;

        if (typeof window.intlTelInput !== "function") {
            console.error("No se ha podido cargar intl-tel-input.");
            return;
        }

        // Recuperar el teléfono guardado en el campo oculto.
        const existingPhone = phoneHidden.value.trim();

        const iti = window.intlTelInput(phoneInput, {
            initialCountry: "es",
            countrySearch: true,
            countryNameLocale: "es",
            separateDialCode: true,
            countrySelectorMode: "dropdown",
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
                console.error(
                    "Error al obtener el teléfono internacional:",
                    error
                );
                phoneHidden.value = "";
            }
        }

        // API utilizada por booking_details.js.
        window.bookingPhone = {
            ready: iti.promise,
            sync: syncPhoneValue
        };

        // Restaurar el teléfono guardado cuando las utilidades estén listas.
        if (existingPhone) {
            iti.promise
                .then(() => {
                    iti.setNumber(existingPhone);
                    phoneHidden.value = iti.getNumber() || existingPhone;
                })
                .catch(error => {
                    console.error(
                        "No se pudo cargar el teléfono guardado.",
                        error
                    );
                });
        }

        phoneInput.addEventListener("input", syncPhoneValue);
        phoneInput.addEventListener("countrychange", syncPhoneValue);

        // En el perfil esperamos a que se carguen las utilidades
        // antes de enviar el formulario.
        if (form.id === "user-profile-form") {
            let resubmitting = false;

            form.addEventListener("submit", async event => {
                if (resubmitting) {
                    resubmitting = false;
                    return;
                }

                event.preventDefault();

                try {
                    await iti.promise;
                    syncPhoneValue();

                    if (!phoneInput.value.trim()) {
                        phoneInput.setCustomValidity(
                            "Introduce un número de teléfono."
                        );
                        phoneInput.reportValidity();
                        return;
                    }

                    phoneInput.setCustomValidity("");

                    if (!iti.isValidNumber()) {
                        phoneInput.setCustomValidity(
                            "Introduce un número de teléfono válido para el país seleccionado."
                        );
                        phoneInput.reportValidity();
                        return;
                    }

                    if (!phoneHidden.value) {
                        phoneInput.setCustomValidity(
                            "No se ha podido obtener el número internacional."
                        );
                        phoneInput.reportValidity();
                        return;
                    }

                    resubmitting = true;
                    form.requestSubmit();
                    resubmitting = false;
                } catch (error) {
                    console.error(
                        "No se pudieron preparar los datos del teléfono:",
                        error
                    );

                    phoneInput.setCustomValidity(
                        "No se ha podido validar el teléfono. Inténtalo de nuevo."
                    );
                    phoneInput.reportValidity();
                }
            });

            phoneInput.addEventListener("input", () => {
                phoneInput.setCustomValidity("");
            });

            phoneInput.addEventListener("countrychange", () => {
                phoneInput.setCustomValidity("");
            });
        }
    });
})();