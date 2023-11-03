import json
import datetime

from os import path
from scipy import stats
from yfpy import Data
from yfpy.logger import get_logger
from yfpy.query import YahooFantasySportsQuery

from nba_api.stats.endpoints import PlayerGameLog, PlayerDashboardByLastNGames, PlayerNextNGames
from nba_api.stats.static import players, teams

class Normal_Distribution:
    def __init__(self, samples=None, num_samples=None, mean=None, variance=None, sd=None):
        if samples:
            self.num_samples = len(samples)
            self.mean = stats.tmean(samples)
            self.variance = stats.tvar(samples)
            self.sd = stats.sqrt(self.variance)

        else:
            self.num_samples = num_samples
            self.mean = mean
            self.variance = variance
            self.sd = sd

    @classmethod
    def combine(cls, dist1, dist2, weight1, weight2):

        num_samples = dist1.num_samples + dist2.num_samples
        mean = dist1.mean * weight1 + dist2.mean * weight2
        variance = (dist1.sd * weight1)^2 + (dist2.sd * weight2)^2
        sd = stats.sqrt(sd)

        return Normal_Distribution(num_samples=num_samples, mean=mean, variance=variance, sd=sd)

class Player:
    def __init__(self, full_name, position, players):
        self.full_name = full_name
        self.position = position
        self.id = players.find_players_by_full_name(full_name)[0]['id']
        self.categories = {}

    def calculate_dist(query, category):
        pass

    def get_category_dists(self, categories, min_mins=7, cume_stats_vs_teams=None, cume_stats_by_location=None):
        cume_stats = {c:[] for c in categories}
        
        for game in PlayerGameLog(player_id=self.id).get_normalized_dict()["PlayerGameLog"]:
            if game['MIN'] < min_mins:
                continue
            _ ,location, opponent = game['MATCHUP'].split(' ')
            for cat in categories:
                cume_stats[cat]['val'].append(game[cat])
                if cume_stats_vs_teams:
                    cume_stats_vs_teams[opponent][cat].append(game[cat])
                if cume_stats_by_location:
                    cume_stats_by_location[location][cat].append(game[cat])

        for cat in categories:
            self.categories[cat] = Normal_Distribution(samples=cume_stats[cat])

class Team:
    def __init__(self, owner_id):
        self.owner_id = owner_id
        self.players = []
        self.category_rankings = {}

class League:
    def __init__(self, auth_dir, league_id, categories):

        with open(path.join(auth_dir, r"private.json")) as f:
            private = json.load(f)
        self.yahoo_query = YahooFantasySportsQuery(
                                auth_dir,
                                league_id,
                                game_code= 'nba',
                                offline=False,
                                all_output_as_json_str=False,
                                consumer_key=private["consumer_key"],
                                consumer_secret=private["consumer_secret"],
                                browser_callback=True)
        self.categories = categories
        
        self.cume_stats_vs_teams = {t['abbreviation']:{c:[] for c in categories} for t in teams.get_teams()}
        self.cume_stats_by_location = {l:{c:[] for c in categories} for l in ['vs', '@']}
        self.players = [Player(p['full_name'], p['position'], players) for p in players.get_players()]

while __name__ != "__main__":
    CATEGORIES = ['PTS', 'REB', 'AST', 'STL', 'BLK', 'TOV', 'FG3M', 'FGM', 'FGA', 'FTM', 'FTA']
    auth_dir = r"auth/"
    league_id = r"101582"
    leauge = League(auth_dir, league_id, CATEGORIES)
