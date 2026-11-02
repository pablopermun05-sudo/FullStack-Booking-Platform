document.addEventListener("click", function (event) {
    const toggle = event.target.closest("[data-proposals-toggle]");

    if (toggle) {
        const panelId = toggle.getAttribute("aria-controls");
        const panel = document.getElementById(panelId);

        if (!panel) return;

        const shouldOpen = !panel.classList.contains("is-open");

        // Cierra los demás paneles
        document.querySelectorAll(".booking-proposals-panel").forEach(function (item) {
            item.classList.remove("is-open");
            item.setAttribute("aria-hidden", "true");

            const button = document.querySelector(
                '[aria-controls="' + item.id + '"]'
            );

            if (button) {
                button.setAttribute("aria-expanded", "false");
            }

            // Oculta el panel después de completar la transición
            if (item !== panel) {
                item.hidden = true;
            }
        });

        if (shouldOpen) {
            // Primero se hace visible y después se inicia la transición
            panel.hidden = false;
            panel.setAttribute("aria-hidden", "false");
            toggle.setAttribute("aria-expanded", "true");

            requestAnimationFrame(function () {
                requestAnimationFrame(function () {
                    panel.classList.add("is-open");
                });
            });
        } else {
            panel.classList.remove("is-open");
            panel.setAttribute("aria-hidden", "true");
            toggle.setAttribute("aria-expanded", "false");

            setTimeout(function () {
                if (!panel.classList.contains("is-open")) {
                    panel.hidden = true;
                }
            }, 190);
        }

        return;
    }

    // Cierra el panel al hacer clic fuera de él
    if (!event.target.closest(".booking-proposals-panel")) {
        document.querySelectorAll(".booking-proposals-panel.is-open").forEach(function (panel) {
            panel.classList.remove("is-open");
            panel.setAttribute("aria-hidden", "true");

            const button = document.querySelector(
                '[aria-controls="' + panel.id + '"]'
            );

            if (button) {
                button.setAttribute("aria-expanded", "false");
            }

            setTimeout(function () {
                if (!panel.classList.contains("is-open")) {
                    panel.hidden = true;
                }
            }, 190);
        });
    }
});