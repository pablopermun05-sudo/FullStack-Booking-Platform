const calendarGrid = document.getElementById(
    "availability-calendar-grid"
);

const availabilityCalendar = document.getElementById(
    "property-availability-calendar"
);

const availabilityResetUrl = availabilityCalendar.dataset.resetUrl;

const defaultPrice = availabilityCalendar.dataset.defaultPrice.replace(",", ".");
const defaultMinNights = availabilityCalendar.dataset.defaultMinNights;

const currentMonthElement = document.getElementById(
    "availability-current-month"
);

const previousYearButton = document.getElementById(
    "availability-previous-year"
);

const previousMonthButton = document.getElementById(
    "availability-previous-month"
);

const nextMonthButton = document.getElementById(
    "availability-next-month"
);

const nextYearButton = document.getElementById(
    "availability-next-year"
);

const availabilityStartDate = document.getElementById(
    "availability-start-date"
);

const availabilityEndDate = document.getElementById(
    "availability-end-date"
);

const availabilityStatus = document.getElementById(
    "availability-status"
);

const availabilityMinNights = document.getElementById(
    "availability-min-nights"
);

const availabilityPrice = document.getElementById(
    "availability-price"
);

const availabilityResetButton = document.getElementById(
    "availability-reset"
);

let currentDate = new Date();

let selectionStart = null;
let selectionEnd = null;

let isDragging = false;
let hasDragged = false;

let availabilityData = {};

const monthFormatter = new Intl.DateTimeFormat("es-ES", {
    month: "long",
    year: "numeric"
});

function formatDate(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");

    return `${year}-${month}-${day}`;
}

async function loadAvailabilityData() {
    const year = currentDate.getFullYear();
    const month = currentDate.getMonth();

    const startDate = formatDate(
        new Date(year, month, 1)
    );

    const endDate = formatDate(
        new Date(year, month + 1, 0)
    );

    const response = await fetch(
        `${availabilityCalendar.dataset.dataUrl}?start_date=${startDate}&end_date=${endDate}`
    );

    if (!response.ok) {
        return;
    }

    const data = await response.json();

    availabilityData = {};

    data.availability.forEach(item => {
        availabilityData[item.date] = item;
    });
}

function isDateSelected(dateString) {
    if (!selectionStart) {
        return false;
    }

    const start = selectionEnd && selectionEnd < selectionStart
        ? selectionEnd
        : selectionStart;

    const end = selectionEnd && selectionEnd < selectionStart
        ? selectionStart
        : selectionEnd || selectionStart;

    return dateString >= start && dateString <= end;
}

function normalizeSelection() {
    if (!selectionStart || !selectionEnd) {
        return;
    }

    if (selectionStart > selectionEnd) {
        [selectionStart, selectionEnd] = [
            selectionEnd,
            selectionStart
        ];
    }
}

function updateSelectionDates() {
    if (!selectionStart) {
        availabilityStartDate.value = "";
        availabilityEndDate.value = "";
        return;
    }

    const start = selectionEnd && selectionEnd < selectionStart
        ? selectionEnd
        : selectionStart;

    const end = selectionEnd && selectionEnd < selectionStart
        ? selectionStart
        : selectionEnd || selectionStart;

    availabilityStartDate.value = start;
    availabilityEndDate.value = end;
}

function clearAvailabilityEditor() {
    availabilityStartDate.value = "";
    availabilityEndDate.value = "";

    availabilityStatus.value = "";
    availabilityMinNights.value = "";
    availabilityPrice.value = "";
}

function selectSingleDay(dateString) {
    selectionStart = dateString;
    selectionEnd = null;

    updateSelectionDates();

    const availability = availabilityData[dateString];

    if (availability) {
        availabilityStatus.value = availability.status;
        availabilityMinNights.value = availability.min_nights;
        availabilityPrice.value = availability.price_per_night;
    } else {
        availabilityStatus.value = "OPEN";
        availabilityMinNights.value = defaultMinNights;
        availabilityPrice.value = defaultPrice;
    }

    renderCalendar();
}

function startRangeSelection(dateString) {
    selectionStart = dateString;
    selectionEnd = dateString;

    isDragging = true;
    hasDragged = false;

    updateSelectionDates();
}

function updateRangeSelection(dateString) {
    if (!isDragging || !selectionStart) {
        return;
    }

    if (dateString !== selectionStart) {
        hasDragged = true;
    }

    selectionEnd = dateString;

    updateSelectionDates();
    renderCalendar();
}

function updateEditorFromRange() {
    if (!selectionStart || !selectionEnd) {
        return;
    }

    const start = selectionStart < selectionEnd
        ? selectionStart
        : selectionEnd;

    const end = selectionStart < selectionEnd
        ? selectionEnd
        : selectionStart;

    const startDate = new Date(start);
    const endDate = new Date(end);

    const values = [];

    for (
        let date = new Date(startDate);
        date <= endDate;
        date.setDate(date.getDate() + 1)
    ) {
        const dateString = formatDate(date);
        const availability = availabilityData[dateString];

        values.push({
            status: availability
                ? availability.status
                : "OPEN",
            minNights: availability
                ? availability.min_nights
                : defaultMinNights,
            price: availability
                ? availability.price_per_night
                : defaultPrice,
        });
    }

    const first = values[0];

    availabilityStatus.value = values.every(
        value => value.status === first.status
    )
        ? first.status
        : "";

    availabilityMinNights.value = values.every(
        value => value.minNights === first.minNights
    )
        ? first.minNights
        : "";

    availabilityPrice.value = values.every(
        value => value.price === first.price
    )
        ? first.price
        : "";
}

function finishRangeSelection() {
    if (!isDragging) {
        return;
    }

    isDragging = false;

    if (!hasDragged) {
        selectionEnd = null;

        const dateString = selectionStart;
        const availability = availabilityData[dateString];

        if (availability) {
            availabilityStatus.value = availability.status;
            availabilityMinNights.value = availability.min_nights;
            availabilityPrice.value = availability.price_per_night;
        } else {
            availabilityStatus.value = "OPEN";
            availabilityMinNights.value = defaultMinNights;
            availabilityPrice.value = defaultPrice;
        }
    } else {
        normalizeSelection();
        updateEditorFromRange();
    }

    updateSelectionDates();
    renderCalendar();
}

function renderCalendar() {
    calendarGrid.innerHTML = "";

    const year = currentDate.getFullYear();
    const month = currentDate.getMonth();

    currentMonthElement.textContent = monthFormatter
        .format(currentDate)
        .replace(/^./, letter => letter.toUpperCase());

    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);

    // Convert Sunday = 0 into Monday = 0.
    const firstWeekday = (firstDay.getDay() + 6) % 7;

    const daysInMonth = lastDay.getDate();

    const weekdays = [
        "Lun",
        "Mar",
        "Mié",
        "Jue",
        "Vie",
        "Sáb",
        "Dom"
    ];

    weekdays.forEach(day => {
        const element = document.createElement("div");

        element.classList.add(
            "availability-calendar-weekday"
        );

        element.textContent = day;

        calendarGrid.appendChild(element);
    });

    for (let i = 0; i < firstWeekday; i++) {
        const element = document.createElement("div");

        element.classList.add(
            "availability-calendar-day",
            "availability-calendar-day-empty"
        );

        calendarGrid.appendChild(element);
    }

    for (let day = 1; day <= daysInMonth; day++) {
        const element = document.createElement("button");

        element.type = "button";

        element.classList.add(
            "availability-calendar-day"
        );

        const date = new Date(year, month, day);
        const dateString = formatDate(date);

        element.textContent = day;
        element.dataset.date = dateString;

        const availability = availabilityData[dateString];

        if (availability) {
            element.dataset.status = availability.status;
        }

        if (availability && availability.status === "CLOSED") {
            const label = document.createElement("span");

            label.classList.add("availability-calendar-day-status");
            label.textContent = "Cerrado";

            element.appendChild(label);
        }

        if (isDateSelected(dateString)) {
            element.classList.add("selected");
        }

        element.addEventListener("mousedown", event => {
            event.preventDefault();
            startRangeSelection(dateString);
        });

        element.addEventListener("mouseenter", () => {
            updateRangeSelection(dateString);
        });

        calendarGrid.appendChild(element);
    }
}

document.addEventListener("mouseup", () => {
    finishRangeSelection();
});

availabilityStartDate.addEventListener("change", () => {
    if (!availabilityStartDate.value) {
        clearAvailabilityEditor();
        selectionStart = null;
        selectionEnd = null;
        renderCalendar();
        return;
    }

    selectionStart = availabilityStartDate.value;

    if (
        availabilityEndDate.value &&
        availabilityEndDate.value < selectionStart
    ) {
        selectionEnd = selectionStart;
    } else {
        selectionEnd = availabilityEndDate.value || selectionStart;
    }

    normalizeSelection();
    updateSelectionDates();
    renderCalendar();
});

availabilityEndDate.addEventListener("change", () => {
    if (!availabilityEndDate.value) {
        selectionEnd = null;

        if (selectionStart) {
            availabilityEndDate.value = selectionStart;
        }

        renderCalendar();
        return;
    }

    selectionEnd = availabilityEndDate.value;

    if (
        selectionStart &&
        selectionEnd < selectionStart
    ) {
        selectionStart = selectionEnd;
    }

    normalizeSelection();
    updateSelectionDates();
    renderCalendar();
});

previousYearButton.addEventListener("click", () => {
    currentDate = new Date(
        currentDate.getFullYear() - 1,
        currentDate.getMonth(),
        1
    );

    loadAvailabilityData().then(() => {
        renderCalendar();
    });
});

previousMonthButton.addEventListener("click", () => {
    currentDate = new Date(
        currentDate.getFullYear(),
        currentDate.getMonth() - 1,
        1
    );

    loadAvailabilityData().then(() => {
        renderCalendar();
    });
});

nextMonthButton.addEventListener("click", () => {
    currentDate = new Date(
        currentDate.getFullYear(),
        currentDate.getMonth() + 1,
        1
    );

    loadAvailabilityData().then(() => {
        renderCalendar();
    });
});

nextYearButton.addEventListener("click", () => {
    currentDate = new Date(
        currentDate.getFullYear() + 1,
        currentDate.getMonth(),
        1
    );

    loadAvailabilityData().then(() => {
        renderCalendar();
    });
});

availabilityResetButton.addEventListener("click", async () => {
    if (!selectionStart) {
        return;
    }

    const startDate = availabilityStartDate.value;
    const endDate = availabilityEndDate.value;

    const confirmed = window.confirm(
        `¿Restaurar los valores por defecto desde ${startDate} hasta ${endDate}?`
    );

    if (!confirmed) {
        return;
    }

    const csrfToken = document.querySelector(
        "[name=csrfmiddlewaretoken]"
    );

    if (!csrfToken) {
        return;
    }

    const response = await fetch(
        availabilityResetUrl,
        {
            method: "POST",
            headers: {
                "X-CSRFToken": csrfToken.value,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            body: new URLSearchParams({
                start_date: startDate,
                end_date: endDate,
            }),
        }
    );

    if (!response.ok) {
        window.alert(
            "No se pudieron restaurar los valores por defecto."
        );
        return;
    }

    const data = await response.json();

    window.alert(
        `Se han eliminado ${data.deleted_count} configuraciones de disponibilidad.`
    );

    await loadAvailabilityData();
    renderCalendar();
});

clearAvailabilityEditor();

loadAvailabilityData().then(() => {
    renderCalendar();
});