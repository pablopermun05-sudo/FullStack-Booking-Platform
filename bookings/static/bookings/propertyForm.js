document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-image-dropzone]").forEach((zone) => {
        const container = zone.closest("[data-image-upload]");
        if (!container) return;

        const input = zone.querySelector("[data-image-input]");
        const previewContainer = container.querySelector(
            "[data-image-preview-container]"
        );
        const preview = container.querySelector("[data-image-preview]");
        const filename = container.querySelector("[data-image-filename]");

        if (!input || !previewContainer || !preview || !filename) return;

        let previewUrl = null;

        function showFile(file) {
            if (!file) return;

            if (!file.type.startsWith("image/")) {
                filename.textContent =
                    "Selecciona un archivo de imagen válido.";
                return;
            }

            if (previewUrl) {
                URL.revokeObjectURL(previewUrl);
            }

            previewUrl = URL.createObjectURL(file);
            preview.src = previewUrl;
            previewContainer.hidden = false;
            filename.textContent = file.name;
        }

        input.addEventListener("change", () => {
            if (input.files.length > 0) {
                showFile(input.files[0]);
            }
        });

        ["dragenter", "dragover"].forEach((eventName) => {
            zone.addEventListener(eventName, (event) => {
                event.preventDefault();
                event.stopPropagation();

                zone.classList.add("is-dragover");

                if (event.dataTransfer) {
                    event.dataTransfer.dropEffect = "copy";
                }
            });
        });

        ["dragleave", "drop"].forEach((eventName) => {
            zone.addEventListener(eventName, (event) => {
                event.preventDefault();
                event.stopPropagation();
                zone.classList.remove("is-dragover");
            });
        });

        zone.addEventListener("drop", (event) => {
            const files = event.dataTransfer?.files;
            if (!files || files.length === 0) return;

            const file = files[0];

            if (!file.type.startsWith("image/")) {
                filename.textContent =
                    "Selecciona un archivo de imagen válido.";
                return;
            }

            try {
                const transfer = new DataTransfer();
                transfer.items.add(file);
                input.files = transfer.files;
            } catch (error) {
                filename.textContent =
                    "No se ha podido cargar el archivo. Prueba a seleccionarlo.";
                return;
            }

            showFile(file);
        });
    });
});