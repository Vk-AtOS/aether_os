"""
Seed template for education domain.
"""
import random
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func
from models import User, Course, Student, Enrollment, Grade

async def seed_education(db_session):
    # 1. Courses (Minimum 5)
    courses = [
        Course(title="Intro to Computer Science", description="Basics of programming", credits=4),
        Course(title="Calculus I", description="Differential calculus", credits=3),
        Course(title="English Literature", description="Modern classics", credits=3),
        Course(title="World History", description="From 1500 to present", credits=3),
        Course(title="Organic Chemistry", description="Molecular structures", credits=4),
        Course(title="Macroeconomics", description="Global markets", credits=3),
        Course(title="Psychology 101", description="Introduction to human behavior", credits=3),
    ]
    db_session.add_all(courses)
    await db_session.flush()

    # 2. Students (Minimum 30)
    students = []
    first_names = ["James", "Mary", "Peter", "Bruce", "Clark", "Diana", "Tony", "Steve", "Natasha", "Wanda", "Barry", "Arthur", "Victor", "Hal", "Oliver", "Kara", "Selina", "Lex", "Lois", "Jimmy"]
    last_names = ["Bond", "Jane", "Parker", "Wayne", "Kent", "Prince", "Stark", "Rogers", "Romanoff", "Maximoff", "Allen", "Curry", "Stone", "Jordan", "Queen", "Danvers", "Kyle", "Luthor", "Lane", "Olsen"]
    for i in range(30):
        name = f"{random.choice(first_names)} {random.choice(last_names)}"
        s = Student(
            full_name=name,
            email=f"student{i+1}@university.edu",
            enrollment_date=datetime.now(timezone.utc).date() - timedelta(days=random.randint(0, 365))
        )
        students.append(s)
    db_session.add_all(students)
    await db_session.flush()

    # 3. Enrollments (Minimum 100)
    enrollments = []
    for i in range(100):
        e = Enrollment(
            student_id=students[i % len(students)].id,
            course_id=courses[i % len(courses)].id,
            status=random.choice(["active", "active", "active", "completed", "dropped"])
        )
        enrollments.append(e)
    db_session.add_all(enrollments)
    await db_session.flush()

    # 4. Grades (Minimum 50)
    for i in range(50):
        g = Grade(
            enrollment_id=enrollments[i % len(enrollments)].id,
            score=random.randint(60, 100),
            comments=random.choice(["Excellent work", "Good progress", "Needs improvement", "Average performance", "Outstanding"])
        )
        db_session.add(g)
    
    await db_session.commit()
