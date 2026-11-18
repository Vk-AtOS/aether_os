"""
Seed template for hrm (Human Resource Management) domain.
"""
from models import Department, Employee, LeaveRequest

async def seed_hrm(db_session):
    # 1. Departments
    depts = [
        Department(name="Engineering", budget=500000),
        Department(name="Sales", budget=300000),
        Department(name="HR", budget=150000),
        Department(name="Marketing", budget=200000),
        Department(name="Product", budget=250000),
    ]
    db_session.add_all(depts)
    await db_session.flush()

    # 2. Employees (FK to Department)
    employees = []
    names = [
        "Alice Smith", "Bob Jones", "Charlie Brown", "David Wilson", "Eve Adams",
        "Frank Miller", "Grace Taylor", "Heidi Davis", "Ivan Thomas", "Judy Garcia",
        "Kevin Martinez", "Laura Robinson", "Mike Clark", "Nina Rodriguez", "Oscar Lewis",
        "Patty Lee", "Quinn Walker", "Rose Hall", "Steve Allen", "Tina Young"
    ]
    for i, name in enumerate(names):
        emp = Employee(
            full_name=name,
            email=f"{name.lower().replace(' ', '.')}@example.com",
            salary=50000 + (i * 2000),
            department_id=depts[i % len(depts)].id
        )
        employees.append(emp)
    db_session.add_all(employees)
    await db_session.flush()

    # 3. Leave Requests (FK to Employee)
    requests = []
    for i in range(30):
        req = LeaveRequest(
            employee_id=employees[i % len(employees)].id,
            start_date="2024-06-01",
            end_date="2024-06-05",
            status="approved" if i % 3 == 0 else "pending",
            reason="Vacation" if i % 2 == 0 else "Sick leave"
        )
        requests.append(req)
    db_session.add_all(requests)
    
    await db_session.commit()
