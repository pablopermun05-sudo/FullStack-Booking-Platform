const calendarGrid = document.getElementById(
    "availability-calendar-grid"
);

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

let currentDate = new Date();

const monthFormatter = new Intl.DateTimeFormat("es-ES", {
    month: "long",
    year: "numeric"
});

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

        element.textContent = day;

        calendarGrid.appendChild(element);
    }
}

previousYearButton.addEventListener("click", () => {
    currentDate = new Date(
        currentDate.getFullYear() - 1,
        currentDate.getMonth(),
        1
    );

    renderCalendar();
});

previousMonthButton.addEventListener("click", () => {
    currentDate = new Date(
        currentDate.getFullYear(),
        currentDate.getMonth() - 1,
        1
    );

    renderCalendar();
});

nextMonthButton.addEventListener("click", () => {
    currentDate = new Date(
        currentDate.getFullYear(),
        currentDate.getMonth() + 1,
        1
    );

    renderCalendar();
});

nextYearButton.addEventListener("click", () => {
    currentDate = new Date(
        currentDate.getFullYear() + 1,
        currentDate.getMonth(),
        1
    );

    renderCalendar();
});

renderCalendar();