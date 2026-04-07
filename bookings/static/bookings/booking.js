document.addEventListener('DOMContentLoaded', () => {
    const alertDiv = document.querySelector('#alert-booking-date');
    const startDate = document.querySelector('#start-date');
    const endDate = document.querySelector('#end-date');

    function validateBooking() {

        if(startDate.value != "" && endDate.value != "") {
            const initialDate = new Date(startDate.value);
            const finalDate = new Date(endDate.value);
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            
            if(initialDate < today) {
                alertDiv.textContent = "La fecha de entrada no puede ser anterior al día de hoy.";
                alertDiv.style.display = 'block';
            } else if(initialDate >= finalDate) {
                alertDiv.textContent = "La fecha de salida debe ser posterior a la de entrada.";
                alertDiv.style.display = 'block';
            } else {
                alertDiv.style.display = 'none';
            }
            
        }
    }

    startDate.addEventListener('change', validateBooking);
    endDate.addEventListener('change', validateBooking);
});