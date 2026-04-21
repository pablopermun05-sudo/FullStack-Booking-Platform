# Alojamiento Vacacional: Advanced Vacation Rental Management Platform

## Project Overview

Alojamiento Vacacional is a full-stack web application designed to manage vacation rental listings and bookings through a modern, scalable, and production-oriented architecture. Developed as the final project for Harvard University's CS50’s Web Programming with Python and JavaScript, the platform focuses on **data integrity, asynchronous interactions, and real-world scalability**.

The application allows users to:

* List and manage rental properties
* Search accommodations using dynamic filters
* Book properties with real-time validation
* Manage their own properties and reservations through personalized dashboards

---

## Tech Stack

* **Backend**: Django (Python)
* **Frontend**: JavaScript (ES6+), HTML5, CSS3, Bootstrap 5
* **Database**: SQLite (development), PostgreSQL-ready

### Libraries

* django-crispy-forms
* django-phonenumber-field

### APIs & Tools

* Fetch API (AJAX)
* Intersection Observer API
* JSON-based internal endpoints

---

## Distinctiveness and Complexity

### Distinctiveness

This project is a vacation rental management system that distinguishes itself from previous CS50W projects through its focus on **temporal data integrity and asynchronous user interaction**.

Unlike Project 2 (Commerce), which manages static product stock, this application handles availability based on **time intervals**. The system enforces strict constraints to ensure that no overlapping bookings exist for the same property, a requirement not present in traditional e-commerce systems.

This introduces constraints closer to real-world reservation systems, where time-based conflicts must be handled at the database level.

Additionally, this project is not a social network (Project 4), as it does not include features such as posts, likes, or follower relationships. Instead, it focuses on **transactional service management**, where correctness and data consistency are critical.

### Complexity

The complexity of the project is built upon three main technical pillars:

#### 1. Asynchronous Booking Engine

The platform uses JavaScript and the Fetch API to perform real-time availability checks and booking confirmations without reloading the page. CSRF tokens are manually handled to maintain Django security standards in an asynchronous environment.

#### 2. Model-Level Integrity (Double-Lock Pattern)

Business logic is enforced directly at the model level using Django’s `clean()` method. Additionally, the `save()` method is overridden to call `full_clean()`, ensuring that validation is always executed regardless of whether data comes from forms, APIs, or the admin panel.

This guarantees that invalid or overlapping bookings can never be stored in the database.

#### 3. Hybrid Architecture (SSR + API-First)

The application combines traditional Django Server-Side Rendering (SSR) for user-related views with an API-first approach for dynamic features like property discovery.

The frontend uses the Intersection Observer API to implement infinite scrolling, significantly improving performance and user experience.

---

## File Documentation

### Backend (Django)

* **models.py**: Defines User, Property, and Booking models. Includes validation logic to prevent negative pricing, invalid guest counts, and overlapping reservations.
* **views.py**: Handles both traditional views (authentication, profiles) and JSON endpoints for searching and booking.
* **urls.py**: Maps all routes, including API endpoints and page views.
* **admin.py**: Configures Django admin interface.
* **tests.py**: Contains unit tests validating booking constraints, data integrity, and edge cases.

### Frontend (JavaScript & CSS)

* **searcher.js**: Implements dynamic filtering and infinite scroll using Intersection Observer.
* **booking.js**: Handles booking logic, date validation, and communication with backend APIs.
* **styles.css**: Defines responsive design and custom UI styling.

### Templates

* **layout.html**: Base template with navigation and shared components.
* **index.html**: Landing page with search functionality and dynamic results.
* **property.html**: Displays property details and booking interface.
* **my_properties.html**: Dashboard for property owners.
* **my_bookings.html**: Dashboard for user reservations.
* **propertyForm.html / userForm.html**: Forms for creating and editing data.

---

## Installation

1. **Clone the repository**:

```bash
git clone https://github.com/pablopermun05-sudo/booking_project
```

2. **Create and activate a virtual environment**:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**:

```bash
pip install -r requirements.txt
```

4. **Database Setup**:

```bash
python manage.py migrate
```

5. **Run the application**:

```bash
python manage.py runserver
```

---

## Testing

Run the test suite with:

```bash
python manage.py test
```

---

## Future Roadmap

* Payment integration (Stripe)
* Real-time chat using Django Channels
* Advanced analytics dashboard for property owners

---

## Demo Video

You can watch a full demonstration of the project at the following link:
https://www.youtube.com/watch?v=J4eDWVUwl0I
