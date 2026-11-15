"""
Seed template for sports domain.
"""
import random
from models import Team, Player, Match, Result

async def seed_sports(db_session):
    # 1. Teams (Minimum 8)
    teams = []
    team_names = ["Hawks", "Eagles", "Lions", "Tigers", "Sharks", "Wolves", "Bears", "Dragons", "Knights", "Titans"]
    for i in range(8):
        t = Team(
            name=f"City {team_names[i]}",
            city=f"City {i+1}"
        )
        teams.append(t)
    db_session.add_all(teams)
    await db_session.flush()

    # 2. Players (Minimum 20)
    players = []
    for i in range(20):
        p = Player(
            full_name=f"Player {i+1}",
            position=random.choice(["Forward", "Midfielder", "Defender", "Goalkeeper"]),
            team_id=teams[i % len(teams)].id
        )
        players.append(p)
    db_session.add_all(players)
    await db_session.flush()

    # 3. Fixtures/Matches (Minimum 15)
    matches = []
    for i in range(15):
        m = Match(
            home_team_id=teams[i % len(teams)].id,
            away_team_id=teams[(i + 1) % len(teams)].id,
            date="2024-06-01",
            venue=f"Stadium {i+1}"
        )
        matches.append(m)
    db_session.add_all(matches)
    await db_session.flush()

    # 4. Match Results (Minimum 10)
    for i in range(10):
        res = Result(
            match_id=matches[i].id,
            home_score=random.randint(0, 5),
            away_score=random.randint(0, 5),
            summary=f"Exciting game between {teams[matches[i].home_team_id-1].name} and {teams[matches[i].away_team_id-1].name}."
        )
        db_session.add(res)
    
    await db_session.commit()
