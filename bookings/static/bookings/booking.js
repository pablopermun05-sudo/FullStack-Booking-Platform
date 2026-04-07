document.addEventListener('DOMContentLoaded', () => {
    const propertyId = document.querySelector('#property-id').value;

    const alertDiv = document.querySelector('#alert-booking-date');
    const buttonDiv = document.querySelector('#booking-button');

    const startDate = document.querySelector('#start-date');
    const endDate = document.querySelector('#end-date');

    function validateBooking() {

        if(startDate.value != "" && endDate.value != "") {
            const initialDate = new Date(startDate.value);
            const finalDate = new Date(endDate.value);
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            
            if(initialDate < today) {
                buttonDiv.style.display = 'none';
                alertDiv.textContent = "La fecha de entrada no puede ser anterior al día de hoy.";
                alertDiv.style.display = 'block';
            } else if(initialDate >= finalDate) {
                buttonDiv.style.display = 'none';
                alertDiv.textContent = "La fecha de salida debe ser posterior a la de entrada.";
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
                        buttonDiv.appendChild(button);
                    }
                    
                })
                .catch(error => {
                    buttonDiv.style.display = 'none';
                    alertDiv.textContent = error.error;
                    alertDiv.style.display = 'block';
                })
            }
            
        }
    }

    startDate.addEventListener('change', validateBooking);
    endDate.addEventListener('change', validateBooking);
});