import json
import datetime
import re
import time
import numpy as np

from os import path
from scipy import stats
from yfpy.query import YahooFantasySportsQuery

from nba_api.stats.endpoints import PlayerGameLog
from nba_api.stats.static import players, teams

POSITIONS = ['PG', 'SG', 'SF', 'PF', 'C']

class Normal_Dist:
    def __init__(self, samples=None, num_samples=None, mean=None, variance=None, sd=None):
        if samples:
            self.num_samples = len(samples)
            self.mean = stats.tmean(samples)
            self.variance = stats.tvar(samples)
            self.sd = np.sqrt(self.variance)

        else:
            self.num_samples = num_samples
            self.mean = mean
            self.variance = variance
            self.sd = sd

    @classmethod
    def weighted_sum(cls, dist1, dist2, weight1, weight2):

        if dist1.num_samples == None:
            return dist2
        elif dist2.num_samples == None:
            return dist1

        num_samples = dist1.num_samples + dist2.num_samples
        mean = dist1.mean * weight1 + dist2.mean * weight2
        variance = dist1.variance * weight1 + dist2.variance * weight2 + weight1 * weight2 * (dist1.mean - dist2.mean)**2
        sd = np.sqrt(variance)

        return Normal_Dist(num_samples=num_samples, mean=mean, variance=variance, sd=sd)
    
    def __add__(self, other):
        
        mean = self.mean + other.mean
        variance = self.variance + other.variance
        sd = np.sqrt(variance)

        return Normal_Dist(mean=mean, variance=variance, sd=sd)
    
    def __sub__(self, other):
        
        mean = self.mean - other.mean
        variance = self.variance + other.variance
        sd = np.sqrt(variance)

        return Normal_Dist(mean=mean, variance=variance, sd=sd)
    
    def __mul__(self, n):
            
        mean = self.mean * n
        variance = self.variance * n
        sd = np.sqrt(variance)

        return Normal_Dist(mean=mean, variance=variance, sd=sd)


class NBAPlayer:
    def __init__(self, full_name, id, position):
        self.full_name = full_name
        self.id = id
        self.position = position
        self.category_dists = {}

    def get_category_dists(self, categories, w1=0.6, w2=0.4, min_mins=7, cume_stats_vs_teams=None, cume_stats_by_location=None):
        start = time.time()
        cume_stats = {c:[] for c in categories}
        cume_stats_prev_season = {c:[] for c in categories}

        for game in PlayerGameLog(player_id=self.id, season='2023').get_normalized_dict()["PlayerGameLog"]:
            if game['MIN'] < min_mins:
                continue
            _ ,location, opponent = game['MATCHUP'].split(' ')
            for cat in categories:
                cume_stats[cat].append(game[cat])
                if cume_stats_vs_teams:
                    cume_stats_vs_teams[opponent][cat][self.position].append(game[cat])
                if cume_stats_by_location:
                    cume_stats_by_location[location][self.position][cat].append(game[cat])
        
        for game in PlayerGameLog(player_id=self.id, season='2022').get_normalized_dict()["PlayerGameLog"]:
            if game['MIN'] < min_mins:
                continue
            _ ,location, opponent = game['MATCHUP'].split(' ')
            for cat in categories:
                cume_stats_prev_season[cat].append(game[cat])
                if cume_stats_vs_teams:
                    cume_stats_vs_teams[opponent][cat][self.position].append(game[cat])
                if cume_stats_by_location:
                    cume_stats_by_location[location][cat][self.position].append(game[cat])

        for cat in categories:
            current_season_dist = Normal_Dist(samples=cume_stats[cat])
            prev_season_dist = Normal_Dist(samples=cume_stats_prev_season[cat])
            self.category_dists[cat] = Normal_Dist.weighted_sum(prev_season_dist, current_season_dist, w1, w2)

        end = time.time()
        duration = end - start
        if duration < 0.6:
            time.sleep(0.6 - duration)

class FantasyTeam:
    def __init__(self, owner_id, owner_nickname):
        self.owner_id = owner_id
        self.owner_nickname = owner_nickname
        self.players = []
        self.summed_category_dists = {}

class FantasyLeague:
    def __init__(self, auth_dir, league_id, game_id, categories):

        with open(path.join(auth_dir, r"private.json")) as f:
            private = json.load(f)
        self.yahoo_query = YahooFantasySportsQuery(
                                auth_dir,
                                league_id,
                                game_code= 'nba',
                                game_id=game_id,
                                offline=False,
                                all_output_as_json_str=False,
                                consumer_key=private["consumer_key"],
                                consumer_secret=private["consumer_secret"],
                                browser_callback=True)
        self.categories = categories

        self.cume_stats_vs_teams = {t['abbreviation']:{p:{c:[] for c in categories} for p in POSITIONS} for t in teams.get_teams()}
        self.cume_stats_by_location = {l:{p:{c:[] for c in categories} for p in POSITIONS} for l in ['vs.', '@']}
        self.nba_players = []
        self.fantasy_teams = []

    def calc_players_stats(self):

        self.nba_players = [NBAPlayer(p.full_name, find_nba_player_id(p.full_name), p.primary_position) for p in self.yahoo_query.get_league_players()]
        self.nba_players = [p for p in self.nba_players if p.id != None]
        for player in self.nba_players:
            player.get_category_dists(self.categories, 0.5, 0.5, 7, self.cume_stats_vs_teams, self.cume_stats_by_location)

    def get_fantasy_teams(self):
        self.fantasy_teams = [FantasyTeam(t.team_id, t.name) for t in self.yahoo_query.get_league_teams()]
        for team in self.fantasy_teams:
            team.players = [p for p in self.nba_players if p.id in [p.id for p in self.yahoo_query.get_team_roster(team.owner_id)]]

    def save_players_stats(self, save_path):
        with open(save_path, 'w') as f:
            json.dump({p.id: {c:{'mean': p.categories[c].mean, 'sd': p.categories[c].sd} for c in p.categories} for p in self.nba_players}, f)

    def load_player_stats(self, save_path):
        with open(save_path) as f:
            player_stats = json.load(f)
        for player in self.nba_players:
            player.categories = {c:Normal_Dist(mean=player_stats[player.id][c]['mean'], sd=player_stats[player.id][c]['sd']) for c in self.categories}

def find_nba_player_id(full_name):
    nba_players = players.get_players()

    search = [player for player in nba_players if player["full_name"] == full_name]
    if len(search) > 0:
        return search[0]['id']

    search = [player for player in nba_players if re.sub('\.|Jr|Sr|II|III|IV| ', '', player["full_name"]) == re.sub('\.|Jr|Sr|II|III|IV| ', '', full_name)]
    if len(search) > 0:
        return search[0]['id']

    else:
        return None


while __name__ == "__main__":

    CATEGORIES = ['PTS', 'REB', 'AST', 'STL', 'BLK', 'TOV', 'FG3M', 'FGM', 'FGA', 'FTM', 'FTA']
    auth_dir = r"auth/"
    league_id = r"101582"
    game_id = 428
    league = FantasyLeague(auth_dir, league_id, game_id, CATEGORIES)
    league.save_players_stats(r"players_stats.json")    

