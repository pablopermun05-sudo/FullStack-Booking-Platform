const noticePeriodDays = parseInt(document.getElementById('notice-period-days').value) || 0;
const defaultMinNights = parseInt(document.getElementById('default-min-nights').value) || 1;
const urlParams = new URLSearchParams(window.location.search);
const initialDate = urlParams.get('initial_date');
const finalDate = urlParams.get('final_date');

if (initialDate && finalDate) {
    document.getElementById('start-date').value = initialDate;
    document.getElementById('end-date').value = finalDate;
}

const availabilityDataFromServer =
    JSON.parse(
        document.getElementById('availability-data').textContent
    );

const bookedDatesFromServer =
    JSON.parse(
        document.getElementById('booked-dates').textContent
    );

let availabilityData = {};

availabilityDataFromServer.forEach(item => {
    availabilityData[item.date] = {
        pricePerNight: Number(item.price_per_night),
        status: item.status,
        minNights: item.min_nights
    };
});

const bookedDates = bookedDatesFromServer;
let selectedMinNights = defaultMinNights;

let picker;

let checkInOnlyDates = [];
let checkoutOnlyDates = [];
let blockedDates = [];
let minStayUnavailableDates = [];
let maxCheckoutDate = null;

function showDateAlert(message) {
    const alertBox = document.getElementById('alert-booking-date');

    if (!alertBox) {
        console.warn('No se encuentra #alert-booking-date');
        return;
    }

    alertBox.textContent = message;
    alertBox.classList.remove('no-display', 'd-none');
}

function hideDateAlert() {
    const alertBox = document.getElementById('alert-booking-date');

    if (alertBox) {
        alertBox.classList.add('no-display');
    }
}

function clearCurrentBookingSelection() {
    const changeForm = document.getElementById('booking-change-form');

    if (changeForm) {
        document.getElementById('start-date').value = '';
        document.getElementById('end-date').value = '';
        document.getElementById('proposed-initial-date').value = '';
        document.getElementById('proposed-final-date').value = '';

        resetProposedBookingPrice();
    } else if (typeof window.clearBookingSelection === 'function') {
        window.clearBookingSelection();
    }
}

function resetProposedBookingPrice() {
    const changeForm = document.getElementById('booking-change-form');

    // No modificar el flujo de las reservas nuevas.
    if (!changeForm) {
        return;
    }

    const totalLabel = document.getElementById('proposed-total-price-label');
    const totalElement = document.getElementById('proposed-total-price');
    const priceBreakdown = document.getElementById('price-breakdown');
    const priceContainer = document.getElementById('proposed-price-container');
    const priceCard = document.getElementById('proposed-price');

    if (totalLabel) {
        totalLabel.textContent = '-';
    }

    if (totalElement) {
        totalElement.textContent = '';
    }

    if (priceBreakdown) {
        priceBreakdown.replaceChildren();
    }

    if (priceContainer) {
        priceContainer.classList.add('d-none');
    }

    if (priceCard) {
        priceCard.classList.remove('show');
    }
}

function getPreviousDate(dateStr) {
    const date = new Date(`${dateStr}T00:00:00`);
    date.setDate(date.getDate() - 1);
    return date.toLocaleDateString('en-CA');
}

function isBooked(dateStr) {
    return bookedDates.includes(dateStr);
}

function isClosed(dateStr) {
    return availabilityData[dateStr]?.status === 'CLOSED';
}

function isAvailableNight(dateStr) {
    return !isBooked(dateStr) && !isClosed(dateStr);
}

function updateProposedBookingPrice(startStr, endStr) {
    // Limitar los cambios a la modificación de reservas.
    const changeForm = document.getElementById('booking-change-form');

    if (!changeForm) {
        return;
    }

    const totalLabel = document.getElementById('proposed-total-price-label');
    const totalElement = document.getElementById('proposed-total-price');
    const priceBreakdown = document.getElementById('price-breakdown');
    const priceContainer = document.getElementById('proposed-price-container');
    const priceCard = document.getElementById('proposed-price');

    if (!totalElement || !priceBreakdown || !priceContainer) {
        return;
    }

    // Restablecer la cotización antes de calcular un nuevo rango.
    priceContainer.classList.add('d-none');

    if (totalLabel) {
        totalLabel.textContent = '-';
    }

    totalElement.textContent = '';
    priceBreakdown.replaceChildren();

    if (priceCard) {
        priceCard.classList.remove('show');
    }

    // Si no hay un rango completo, no mostrar la cotización.
    if (!startStr || !endStr) {
        return;
    }

    const currentDate = new Date(`${startStr}T00:00:00`);
    const checkoutDate = new Date(`${endStr}T00:00:00`);

    if (
        Number.isNaN(currentDate.getTime()) ||
        Number.isNaN(checkoutDate.getTime()) ||
        currentDate >= checkoutDate
    ) {
        return;
    }

    // Generar fechas YYYY-MM-DD independientemente del idioma del navegador.
    function formatDateKey(date) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');

        return `${year}-${month}-${day}`;
    }

    const nights = [];
    let total = 0;

    // La entrada se incluye y la salida se excluye.
    while (currentDate < checkoutDate) {
        const dateStr = formatDateKey(currentDate);
        const nightData = availabilityData[dateStr];

        if (
            !nightData ||
            nightData.pricePerNight == null ||
            !Number.isFinite(Number(nightData.pricePerNight))
        ) {
            console.error('No se ha encontrado el precio de una noche:', {
                fecha: dateStr,
                datosEncontrados: nightData
            });

            return;
        }

        const nightlyPrice = Number(nightData.pricePerNight);

        nights.push({
            date: dateStr,
            price: nightlyPrice
        });

        total += nightlyPrice;
        currentDate.setDate(currentDate.getDate() + 1);
    }

    // Crear el desglose por noche.
    const fragment = document.createDocumentFragment();

    nights.forEach(night => {
        const [year, month, day] = night.date.split('-');
        const row = document.createElement('div');

        row.className = 'd-flex justify-content-between align-items-center mb-2';

        const dateLabel = document.createElement('span');
        dateLabel.textContent = `Noche del ${day}/${month}/${year}`;

        const priceLabel = document.createElement('span');
        priceLabel.textContent = `${night.price.toLocaleString('es-ES', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        })} €`;

        row.append(dateLabel, priceLabel);
        fragment.appendChild(row);
    });

    priceBreakdown.appendChild(fragment);

    const formattedTotal = `${total.toLocaleString('es-ES', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    })} €`;

    totalElement.textContent = formattedTotal;

    if (totalLabel) {
        totalLabel.textContent = formattedTotal;
    }

    // Mostrar la cotización únicamente tras un cálculo correcto.
    priceContainer.classList.remove('d-none');

    console.log('Cotización calculada:', {
        entrada: startStr,
        salida: endStr,
        noches: nights.length,
        total
    });
}

const minBookingDate = new Date();
minBookingDate.setHours(0, 0, 0, 0);
minBookingDate.setDate(minBookingDate.getDate() + noticePeriodDays);
const minBookingDateStr = minBookingDate.toLocaleDateString('en-CA'); // Formato "YYYY-MM-DD"

checkInOnlyDates = [];
checkoutOnlyDates = [];
blockedDates = [];
minStayUnavailableDates = [];

Object.keys(availabilityData)
    .filter(dateStr => dateStr >= minBookingDateStr)
    .forEach(dateStr => {

        const previousDate = getPreviousDate(dateStr);

        const currentNightAvailable =
            isAvailableNight(dateStr);

        const previousNightAvailable =
            isAvailableNight(previousDate);

        const minNights =
            availabilityData[dateStr]?.minNights ||
            defaultMinNights;

        let minStayBlocked = false;

        for (let i = 0; i < minNights; i++) {

            const nightDate =
                new Date(`${dateStr}T00:00:00`);

            nightDate.setDate(
                nightDate.getDate() + i
            );

            const nightDateStr =
                nightDate.toLocaleDateString('en-CA');

            if (!isAvailableNight(nightDateStr)) {
                minStayBlocked = true;
                break;
            }
        }

        if (minStayBlocked) {
            minStayUnavailableDates.push(dateStr);
        }

        if (
            !currentNightAvailable &&
            previousNightAvailable
        ) {
            checkoutOnlyDates.push(dateStr);
            return;
        }

        if (
            currentNightAvailable &&
            !previousNightAvailable
        ) {
            checkInOnlyDates.push(dateStr);
            return;
        }

        if (
            !currentNightAvailable &&
            !previousNightAvailable
        ) {
            blockedDates.push(dateStr);
        }
    });

picker = initializePicker();

function initializePicker() {

    const lockedDates = blockedDates.map(date => [date, date]);

    const picker = new Litepicker({
        element: document.getElementById('booking-range'),
        parentEl: document.getElementById('booking-calendar'),

        inlineMode: true,
        singleMode: false,

        numberOfMonths: 1,
        numberOfColumns: 1,

        format: 'DD/MM/YYYY',

        minDate: minBookingDateStr,
        minDays: 2,

        startDate: initialDate || undefined,
        endDate: finalDate || undefined,

        lockDays: lockedDates,
        bookedDays: checkoutOnlyDates,
        disallowedDatesRanges: lockedDates,

        selectForward: true,
        lockDaysInversed: false,

        tooltipText: {
            one: 'noche',
            other: 'noches'
        },

        tooltipNumber: (totalDays) => {
            const nights = totalDays - 1;

            if (nights < selectedMinNights) {
                return selectedMinNights;
            }

            return nights;
        },

        setup: (picker) => {
            picker.on('tooltip', (tooltip, dayElement) => {
                if (!selectedMinNights) {
                    return;
                }

                if (!picker.datePicked || picker.datePicked.length !== 1) {
                    return;
                }

                const start = picker.datePicked[0].toJSDate();
                const hoveredDate = new Date(Number(dayElement.dataset.time));

                const nights = Math.round((hoveredDate - start) / (1000 * 60 * 60 * 24));

                if (nights < selectedMinNights) {
                    tooltip.textContent = `Estancia mínima: ${selectedMinNights} noches`;
                    dayElement.classList.remove('is-end-date', 'is-flipped');

                    const containerRect = picker.ui.getBoundingClientRect();
                    const tooltipRect = tooltip.getBoundingClientRect();
                    const dayRect = dayElement.getBoundingClientRect();

                    let top = dayRect.top - containerRect.top;
                    let left = dayRect.left - containerRect.left;

                    top -= tooltipRect.height;
                    left -= tooltipRect.width / 2;
                    left += dayRect.width / 2;

                    tooltip.style.top = `${top}px`;
                    tooltip.style.left = `${left}px`;
                }
            });

            picker.on('preselect', (date1, date2) => {

                if (!date1) {
                    return;
                }

                const startStr = date1.format('YYYY-MM-DD');
                const alertBox = document.getElementById('alert-booking-date');
                const selectedDate = date1.toJSDate();
                const today = new Date();

                today.setHours(0, 0, 0, 0);
                selectedDate.setHours(0, 0, 0, 0);

                if (selectedDate < today) {
                    alertBox.textContent = 'Fecha pasada.';
                    alertBox.classList.remove('no-display');

                    picker.clearSelection();
                    clearCurrentBookingSelection();
                    return;
                }

                const earliestDate = new Date(today);
                earliestDate.setDate(earliestDate.getDate() + noticePeriodDays);

                if (selectedDate < earliestDate) {
                    alertBox.textContent =
                        `Debes reservar con al menos ${noticePeriodDays} días de antelación.`;
                    alertBox.classList.remove('no-display');

                    picker.clearSelection();
                    clearCurrentBookingSelection();
                    return;
                }

                if (checkoutOnlyDates.includes(startStr)) {
                    picker.clearSelection();
                    clearCurrentBookingSelection();
                    return;
                }

                if (minStayUnavailableDates.includes(startStr)) {
                    const minNights =
                        availabilityData[startStr]?.minNights || defaultMinNights;

                    picker.clearSelection();

                    clearCurrentBookingSelection();

                    if (typeof showDateAlert === 'function') {
                        showDateAlert(`Estancia mínima de ${minNights} noches.`);
                    } else {
                        const alertBox = document.getElementById('alert-booking-date');

                        if (alertBox) {
                            alertBox.textContent = `Estancia mínima de ${minNights} noches.`;
                            alertBox.classList.remove('no-display', 'd-none');
                        }
                    }

                    return;
                }

                if (!date2) {
                    const minNights = availabilityData[startStr]?.minNights || defaultMinNights;
                    selectedMinNights = minNights;

                    const firstCheckoutOnlyDate = checkoutOnlyDates
                        .filter(date => date > startStr)
                        .sort()[0];

                    maxCheckoutDate = firstCheckoutOnlyDate || null;

                    picker.setOptions({
                        maxDate: maxCheckoutDate
                            ? new Date(`${maxCheckoutDate}T00:00:00`)
                            : null
                    });

                    picker.gotoDate(selectedDate);
                    return;
                }

                const nights = date2.diff(date1, 'day');

                if (
                    maxCheckoutDate &&
                    date2.format('YYYY-MM-DD') > maxCheckoutDate
                ) {
                    picker.datePicked.length = 1;
                    picker.render();
                    return;
                }

                if (nights < selectedMinNights) {
                    picker.datePicked.length = 1;
                    picker.render();
                    return;
                }
            });

            picker.on('render:day', (dayElement, date) => {
                const dStr = date.format('YYYY-MM-DD');

                if (
                    picker.datePicked &&
                    picker.datePicked.length > 0 &&
                    picker.datePicked[0].format('YYYY-MM-DD') === dStr
                ) {
                    dayElement.addEventListener('click', (event) => {
                        event.preventDefault();
                        event.stopPropagation();

                        // Guardamos el día que estaba seleccionado
                        const selectedDate = date.toJSDate();

                        // Restablecer primero las restricciones del calendario
                        maxCheckoutDate = null;
                        selectedMinNights = defaultMinNights;

                        picker.setOptions({
                            maxDate: null
                        });

                        picker.clearSelection();

                        // Restablecer la cotización al deseleccionar las fechas.
                        resetProposedBookingPrice();

                        picker.gotoDate(selectedDate);

                        // Limpiar los campos según el formulario actual
                        if (document.getElementById('booking-change-form')) {
                            document.getElementById('start-date').value = '';
                            document.getElementById('end-date').value = '';
                            document.getElementById('proposed-initial-date').value = '';
                            document.getElementById('proposed-final-date').value = '';
                        } else if (typeof window.clearBookingSelection === 'function') {
                            clearCurrentBookingSelection();
                        }

                        // Mantener el calendario en el mes actual
                        picker.gotoDate(selectedDate);
                    });
                }

                if (blockedDates.includes(dStr)) {
                    dayElement.classList.add('availability-locked');
                }

                if (minStayUnavailableDates.includes(dStr)) {
                    const hasCheckIn =
                        picker.datePicked &&
                        picker.datePicked.length === 1;

                    const selectedCheckIn = hasCheckIn
                        ? picker.datePicked[0].format('YYYY-MM-DD')
                        : null;

                    const canBeCheckout =
                        hasCheckIn &&
                        dStr > selectedCheckIn &&
                        !checkInOnlyDates.includes(dStr) &&
                        !blockedDates.includes(dStr) &&
                        (!maxCheckoutDate || dStr <= maxCheckoutDate);

                    if (canBeCheckout) {
                        dayElement.classList.remove('min-stay-unavailable');
                    } else {
                        dayElement.classList.add('min-stay-unavailable');
                    }
                }

                if (checkoutOnlyDates.includes(dStr)) {
                    dayElement.classList.add('solo-salida');
                } else if (checkInOnlyDates.includes(dStr)) {
                    dayElement.classList.add('solo-entrada');
                }

                const dayDate = date.toJSDate();
                const today = new Date();

                today.setHours(0, 0, 0, 0);
                dayDate.setHours(0, 0, 0, 0);

                if (dayDate < today) {
                    dayElement.addEventListener('click', (event) => {
                        event.preventDefault();
                        event.stopPropagation();

                        picker.clearSelection();
                        clearCurrentBookingSelection();
                        showDateAlert('Fecha pasada.');
                    });
                } else if (dayDate < minBookingDate) {
                    dayElement.addEventListener('click', (event) => {
                        event.preventDefault();
                        event.stopPropagation();

                        const dayText = noticePeriodDays === 1 ? 'día' : 'días';

                        picker.clearSelection();
                        clearCurrentBookingSelection();

                        showDateAlert(
                            `Debes reservar con al menos ${noticePeriodDays} ${dayText} de antelación.`
                        );
                    });
                }
            });

            picker.on('selected', (date1, date2) => {
                const startStr = date1.format('YYYY-MM-DD');
                const endStr = date2.format('YYYY-MM-DD');

                const alertBox = document.getElementById(
                    'alert-booking-date'
                );

                let currentDate = new Date(`${startStr}T00:00:00`);
                const checkoutDate = new Date(`${endStr}T00:00:00`);

                while (currentDate < checkoutDate) {
                    const currentDateStr =
                        currentDate.toLocaleDateString('en-CA');

                    if (!isAvailableNight(currentDateStr)) {
                        alertBox.textContent =
                            'El rango seleccionado contiene una noche no disponible.';
                        alertBox.classList.remove('no-display');
                        picker.clearSelection();
                        clearCurrentBookingSelection();
                        return;
                    }

                    currentDate.setDate(currentDate.getDate() + 1);
                }

                if (
                    checkoutOnlyDates.includes(startStr) ||
                    checkInOnlyDates.includes(endStr)
                ) {
                    alertBox.textContent =
                        'La combinación de fechas no es válida: revisa el día marcado en rojo en diagonal.';
                    alertBox.classList.remove('no-display');
                    picker.clearSelection();
                    clearCurrentBookingSelection();
                    return;
                }

                picker.setOptions({
                    maxDate: null
                });

                maxCheckoutDate = null;

                alertBox.classList.add('no-display');

                const startInput = document.getElementById('start-date');
                const endInput = document.getElementById('end-date');

                startInput.value = startStr;
                endInput.value = endStr;

                const changeForm = document.getElementById('booking-change-form');

                if (changeForm) {
                    document.getElementById('proposed-initial-date').value = startStr;
                    document.getElementById('proposed-final-date').value = endStr;

                    updateProposedBookingPrice(startStr, endStr);

                    changeForm.dispatchEvent(new Event('bookingDatesChanged'));
                } else if (typeof window.validateBooking === 'function') {
                    window.validateBooking();
                }
            });
        }
    });

    return picker;
}