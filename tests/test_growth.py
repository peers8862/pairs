from decimal import Decimal as D

from lib import growth as G


def model(**kw):
    m = {'start': '2027-01', 'months': 3,
         'channels': [{'name': 'Ads', 'type': 'paid_cpa', 'spend': 1000, 'cpa': 10}],
         'funnel': {'activation': 0.5, 'paid_conversion': 0.2}, 'retention': [0.5],
         'revenue': {'tiers': [{'name': 'A', 'price': 10, 'share': 1}]}, 'cost_to_serve': 2}
    m.update(kw)
    return m


def test_cohorts_shrink_and_revenue_follows():
    rows, ue = G.run(model())
    # 100 sign-ups/month -> 10 new paying; retention 50% month on month
    assert [round(r['paying'], 4) for r in rows] == [D(10), D(15), D('17.5')]
    assert rows[2]['revenue'] == D('175.0')
    assert rows[0]['contribution'] == D(100) - D(1000) - D(20)
    assert ue['cac'] == D(100) and ue['gross_margin'] == D('0.8')
    assert round(ue['expected_lifetime_months'], 6) == D(2)          # 1 + 0.5 + 0.25 + ...
    assert round(ue['ltv'], 2) == D('16.00')


def test_paid_funnel_and_spend_growth():
    m = model(channels=[{'name': 'Search', 'type': 'paid', 'spend': 1200, 'spend_growth': 0.5, 'cpm': 12,
                         'ctr': 0.02, 'conversion': 0.1}])
    rows, _ = G.run(m)
    assert rows[0]['signups'] == D('200') and rows[1]['spend'] == D('1800.0')


def test_viral_builds_on_previous_month():
    m = model(channels=[{'type': 'paid_cpa', 'name': 'Ads', 'spend': 1000, 'cpa': 10},
                        {'type': 'viral', 'name': 'Invites', 'invites': 2, 'invite_conversion': 0.25}])
    rows, _ = G.run(m)
    assert rows[0]['signups'] == D(100) and rows[1]['signups'] == D(150) and rows[2]['signups'] == D(175)


def test_sales_reps_ramp_and_partners():
    m = model(channels=[{'type': 'sales', 'name': 'Sales', 'reps': 1, 'deals_per_rep': 4, 'ramp_months': 2,
                         'cost_per_rep': 5000},
                        {'type': 'partners', 'name': 'P', 'partners': 1, 'new_partners': 1, 'users_per_partner': 10}])
    rows, _ = G.run(m)
    assert rows[0]['by_channel']['Sales']['paying'] == D(2) and rows[1]['by_channel']['Sales']['paying'] == D(4)
    assert rows[0]['sales_cost'] == D(5000)
    assert rows[1]['by_channel']['P']['signups'] == D(20)


def test_validation_and_occurrences():
    assert G.validate(model(retention=[1.5]))
    assert G.validate(model(channels=[{'type': 'tv'}]))
    assert G.validate({'start': 'soon'})
    occ = G.occurrences(model())
    kinds = {(o['kind'], o['account']) for o in occ}
    assert ('revenue', 'Income:Operating:Sales') in kinds and ('expense', 'Expenses:Operating:Marketing') in kinds
    assert occ[0]['date'].isoformat() == '2027-01-01'
    assert G.occurrences(model(retention=[2])) == []
