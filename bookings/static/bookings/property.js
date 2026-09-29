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
                    window.clearBookingSelection();
                    return;
                }

                const earliestDate = new Date(today);
                earliestDate.setDate(earliestDate.getDate() + noticePeriodDays);

                if (selectedDate < earliestDate) {
                    alertBox.textContent =
                        `Debes reservar con al menos ${noticePeriodDays} días de antelación.`;
                    alertBox.classList.remove('no-display');

                    picker.clearSelection();
                    window.clearBookingSelection();
                    return;
                }

                if (checkoutOnlyDates.includes(startStr)) {
                    picker.clearSelection();
                    window.clearBookingSelection();
                    return;
                }

                if (minStayUnavailableDates.includes(startStr)) {
                    const minNights = availabilityData[startStr]?.minNights || defaultMinNights;

                    picker.clearSelection();
                    window.clearBookingSelection();

                    alertBox.textContent = `Estancia mínima de ${minNights} noches.`;
                    alertBox.classList.remove('no-display');

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

                        // Cancelar la selección y limpiar el estado de reserva
                        picker.clearSelection();
                        window.clearBookingSelection();

                        maxCheckoutDate = null;

                        picker.setOptions({
                            maxDate: null
                        });

                        // Restaurar la estancia mínima por defecto
                        selectedMinNights = defaultMinNights;

                        // Volver al mes donde estaba el usuario
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
                    dayElement.addEventListener('click', () => {
                        const alertBox = document.getElementById('alert-booking-date');

                        picker.clearSelection();
                        window.clearBookingSelection();

                        alertBox.textContent = 'Fecha pasada.';
                        alertBox.classList.remove('no-display');
                    });
                } else if (dayDate < minBookingDate) {
                    dayElement.addEventListener('click', () => {
                        const alertBox = document.getElementById('alert-booking-date');
                        const dayText = noticePeriodDays === 1 ? 'día' : 'días';

                        picker.clearSelection();
                        window.clearBookingSelection();

                        alertBox.textContent =
                            `Debes reservar con al menos ${noticePeriodDays} ${dayText} de antelación.`;
                        alertBox.classList.remove('no-display');
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
                        window.clearBookingSelection();
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
                    window.clearBookingSelection();
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

                window.validateBooking();
            });
        }
    });

    return picker;
}