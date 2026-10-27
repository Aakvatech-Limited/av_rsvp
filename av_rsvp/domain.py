"""Framework-independent input and capacity rules, also used by the service layer."""

from datetime import datetime
from zoneinfo import ZoneInfo

RESPONSES = {"Attending", "Declined", "Maybe"}


def event_now(timezone):
    return datetime.now(ZoneInfo(timezone)).replace(tzinfo=None)


def allocation_for(attendance, already_confirmed, capacity, used, waitlist):
    if attendance != "Attending":
        return "Cancelled" if attendance == "Declined" else "Unallocated"
    if already_confirmed or not capacity or used < capacity:
        return "Confirmed"
    if waitlist:
        return "Waitlisted"
    raise ValueError("This function has reached capacity.")


def clean_text(value, maximum=140):
    if not isinstance(value, str) or len(value.strip()) > maximum or "\x00" in value:
        raise ValueError(f"Text must contain at most {maximum} characters.")
    return value.strip()


def validate_people(people, maximum, functions, allow_maybe):
    if not isinstance(people, list) or len(people) > maximum:
        raise ValueError("The number of people exceeds this invitation's allowance.")
    seen = set()
    for person in people:
        if not isinstance(person, dict):
            raise ValueError("Invalid attendee.")
        if not clean_text(person.get("attendee_name", "")):
            raise ValueError("An attendee name is required.")
        if person.get("age_group", "Adult") not in {"Adult", "Child"}:
            raise ValueError("Choose Adult or Child.")
        for key in ("dietary_requirements", "accessibility_requests"):
            clean_text(person.get(key, ""), 1000)
        if person.get("name"):
            if person["name"] in seen:
                raise ValueError("An attendee appears more than once.")
            seen.add(person["name"])
        answers = person.get("functions", [])
        if not isinstance(answers, list) or len(answers) != len(functions):
            raise ValueError("Respond to every available function for each attendee.")
        answered = set()
        for answer in answers:
            if not isinstance(answer, dict):
                raise ValueError("Invalid function response.")
            function = answer.get("function")
            if function not in functions or function in answered:
                raise ValueError("Invalid or repeated function.")
            answered.add(function)
            attendance = answer.get("attendance")
            if attendance not in RESPONSES or (attendance == "Maybe" and not allow_maybe):
                raise ValueError("Invalid attendance response.")
            meal = clean_text(answer.get("meal_choice", ""))
            choices = [
                line.strip()
                for line in (functions[function].get("meal_options") or "").splitlines()
                if line.strip()
            ]
            if meal and meal not in choices:
                raise ValueError("Choose a meal from the available options.")
            if attendance == "Attending" and choices and not meal:
                raise ValueError("Choose a meal for each attending guest.")
