# Alojamiento Vacacional: Advanced Vacation Rental Management Platform

## Project Overview
Alojamiento Vacacional is a professional-grade, full-stack web application designed to facilitate vacation rental management. Built as the final project for Harvard University's CS50’s Web Programming with Python and JavaScript, the platform focuses on high-performance user interactions, robust data integrity, and a modern, asynchronous architectural style.

The application allows users to list properties, search for accommodations using dynamic filters, and manage bookings through a custom-built asynchronous engine.

---

## Tech Stack

Backend: Django (Python)  
Frontend: JavaScript (ES6+), Bootstrap 5, CSS3  
Database: SQLite (development), PostgreSQL (production-ready)  
APIs & Tools: Django Crispy Forms, Phonenumbers library, Intersection Observer API, JSON endpoints  

---

## Technical Deep Dive

### 1. High-Integrity Data Model (Backend)
Alojamiento Vacacional prioritizes data consistency by implementing validation at the model level rather than relying solely on form or frontend checks.

* **Custom Validation Logic**: The `Property` and `Booking` models use the `clean()` method to enforce business rules. For instance, it prevents negative pricing, ensures at least one adult per property, and validates that the checkout date is after the check-in date.
* **The "Double-Lock" Integrity Pattern**: To ensure these rules are always respected—whether data comes from a form, the admin panel, or an API—the `save()` method is overridden to call `full_clean()` before committing to the database.
* **Booking Overlap Prevention**: The system uses complex queryset filtering (`initial_date__lt=self.final_date` and `final_date__gt=self.initial_date`) to ensure no two bookings for the same property can overlap.
* **Standardized Contact Data**: Integration of `PhoneNumberField` to ensure all user contact information adheres to international telecommunication standards (E.164) directly at the database level.

---

### 2. Infinite Scroll & Dynamic Discovery
To provide a fluid user experience similar to industry leaders, Alojamiento Vacacional utilizes the **Intersection Observer API**.

* **Asynchronous Loading**: The `searcher.js` script monitors the user's scroll position. When the last property card enters the viewport, a `fetch` request is triggered to the `/properties/` API endpoint to load the next page of results.
* **Performance**: This approach reduces initial page load times and eliminates the need for traditional pagination buttons.

---

### 3. Asynchronous Booking Engine
The booking flow is managed entirely via JavaScript to provide instant feedback without page refreshes.

* **Real-Time Availability**: As users select dates in `property.html`, `booking.js` performs background checks against the server to verify availability.
* **Security**: All POST requests for booking confirmations are secured with CSRF tokens retrieved from document cookies, maintaining Django's security standards within a decoupled JavaScript workflow.
* **Business Restrictions**: The system automatically prevents owners from booking their own properties and hides booking controls if the user is not authenticated.

---

### 4. Advanced Search and Filtering
The search engine allows for granular filtering through a dedicated API-driven interface.

* **Multi-Criteria Filtering**: Users can filter by location, date range, guest capacity (adults/children), room count, and pet friendliness.
* **State Management**: The search form intercepts the `submit` event to update the UI dynamically via `searcher.js`, preventing a full page reload.

---

## Distinctiveness and Complexity

Alojamiento Vacacional exceeds the standard requirements of the CS50W curriculum by implementing:

1. **Model-Level Enforcement**: Moving logic from views/forms into models via `full_clean()` to ensure database-wide integrity regardless of the data source.  
2. **API-First Approach**: Leveraging internal API routes to handle searching and booking, moving the application toward a modern "headless" architecture.  
3. **Modern JavaScript APIs**: Utilizing the `IntersectionObserver` API for performance-oriented UI patterns.  
4. **Complex Logic**: Handling multi-user interactions where roles (Owner vs. Tenant) dictate interface availability and permissions.  

---

## File Architecture & Responsibilities

* **models.py**: Defines the core schema and houses the primary business logic through custom clean methods.  
* **views.py**: Contains a mix of traditional SSR views for profile management and JSON API endpoints for property discovery and booking.  
* **booking.js**: Orchestrates the client-side booking logic, date validation, and server communication.  
* **searcher.js**: Manages the Infinite Scroll observer and the dynamic rendering of property cards.  
* **tests.py**: Comprehensive test suite that validates critical business constraints, including price boundaries, minimum guest requirements, and the atomic logic for preventing booking collisions.  

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

## Future Roadmap

* **Payment Integration**: Implementing Stripe API for secure transaction handling.  
* **Internal Messaging**: Developing a real-time chat system between owners and tenants using Django Channels.  
* **Advanced Analytics**: Host dashboard with occupancy rates and revenue projections.  

---

## Testing

```bash
python manage.py test
```
