let successBooking = false;

document.addEventListener('DOMContentLoaded', () => {
    const propertyId = document.querySelector('#property-id').value;

    const alertDiv = document.querySelector('#alert-booking-date');
    const buttonDiv = document.querySelector('#booking-button');
    const datesDiv = document.querySelector('#datesDiv');
    const occupiedDatesCard = document.querySelector('#occupied-dates-card');

    const startDate = document.querySelector('#start-date');
    const endDate = document.querySelector('#end-date');

    // Function to get the CSRF token from cookies
    // This is needed because {% csrf_token %} only works in HTML files
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    const csrftoken = getCookie('csrftoken');

    function confirmBooking(start, end) {
        if (!successBooking) {
            const url = `/confirm_booking/${propertyId}`;
            fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrftoken },
                body: JSON.stringify({
                    start: start,
                    end: end
                })
            })
                .then(response => {
                    if (!response.ok) {
                        return response.json().then(err => { throw err; });
                    }
                    return response.json();
                })
                .then(data => {
                    if(data.success) {
                        window.location.href = "/my_bookings";
                    }
                })
                .catch(error => {
                    buttonDiv.style.display = 'none';
                    alertDiv.textContent = error.error || "Error al procesar la reserva.";
                    alertDiv.style.display = 'block';
                });
        }
    }

    function validateBooking() {
        if (startDate.value != "" && endDate.value != "") {
            const initialDate = new Date(startDate.value);
            const finalDate = new Date(endDate.value);
            const today = new Date();
            today.setHours(0, 0, 0, 0);

            if (initialDate < today) {
                buttonDiv.style.display = 'none';
                alertDiv.textContent = "La fecha de entrada no puede ser anterior al día de hoy.";
                alertDiv.style.display = 'block';
            } else if (initialDate > finalDate) {
                buttonDiv.style.display = 'none';
                alertDiv.textContent = "La fecha de salida debe ser igual o posterior a la de entrada.";
                alertDiv.style.display = 'block';
            } else {
                alertDiv.style.display = 'none';
                buttonDiv.textContent = "Cargando disponibilidad...";
                buttonDiv.style.display = 'block';

                const url = `/booking/${propertyId}/?start=${startDate.value}&end=${endDate.value}`;
                fetch(url)
                    .then(response => {
                        if (!response.ok) {
                            // Extracting JSON error details before throwing to the catch block.
                            return response.json().then(err => { throw err; });
                        }
                        return response.json();
                    })
                    .then(data => {
                        buttonDiv.textContent = "";

                        if (data.available) {
                            const button = document.createElement('button');
                            button.textContent = "Confirmar Reserva";
                            button.className = "btn btn-dark w-100 rounded-pill mt-3 mb-3 py-2";
                            button.addEventListener('click', () => {
                                button.disabled = true;
                                button.textContent = "Procesando...";
                                confirmBooking(startDate.value, endDate.value);
                            });
                            buttonDiv.appendChild(button);
                        }

                    })
                    .catch(error => {
                        buttonDiv.style.display = 'none';
                        alertDiv.textContent = error.error || "Error inesperado.";
                        alertDiv.style.display = 'block';
                    })
            }

        }
    }

    startDate.addEventListener('change', validateBooking);
    endDate.addEventListener('change', validateBooking);
});