"""Fundraising — rounds, the investor pipeline, commitments and momentum.

    fundraising/rounds.yaml     [{id, name, type, instrument, target, close_date, status,
                                  pre_money, price, cap, discount, interest, post_money, notes}]
    fundraising/pipeline.yaml   [{id, investor, email, organization, investor_type, referral,
                                  round, stage, amount, first_meeting, last_meeting, next_step,
                                  history: [{date, stage}], notes: [{date, text, meeting}]}]

Stages and investor types are defaults that a company can replace in its
config.yaml (fundraising: {stages: [...], investor_types: [...]}).
"""

from datetime import date
from decimal import Decimal

from lib.journal import build_tags

STAGES = ['1st call', '2nd call', 'due diligence', 'documents requested', 'soft committed',
          'agreement sent', 'signed', 'capital received']
CLOSED_LOST = 'passed'
INVESTOR_TYPES = ['angel (family)', 'angel (pro)', 'angel (super)', 'angel group', 'VC',
                  'private equity', 'family office', 'corporate venture', 'other']
ROUND_TYPES = ['pre-seed', 'seed', 'series-a', 'series-b', 'bridge', 'other']
INSTRUMENTS = ['equity', 'safe', 'note', 'debt', 'grant']
FUNDING_ACCOUNTS = {
    'equity': ('Equity:Share Capital', '1001'),
    'safe': ('Equity:SAFE', '1001'),
    'note': ('Liabilities:Long-Term:Convertible Notes', '1000'),
    'debt': ('Liabilities:Long-Term:Loans', '1000'),
    'grant': ('Income:Other:Grants', '1001'),
}
ZERO = Decimal('0')


def stages(config=None):
    custom = ((config or {}).get('fundraising') or {}).get('stages')
    return list(custom) if custom else list(STAGES)


def investor_types(config=None):
    custom = ((config or {}).get('fundraising') or {}).get('investor_types')
    return list(custom) if custom else list(INVESTOR_TYPES)


def stage_rank(stage, config=None):
    st = stages(config)
    return st.index(stage) if stage in st else -1


def at_least(stage, floor, config=None):
    return stage != CLOSED_LOST and stage_rank(stage, config) >= stage_rank(floor, config)


def progress(round_, deals, config=None):
    """Target vs soft-committed, signed and received for one round."""
    mine = [d for d in deals if d.get('round') == round_['id']]
    amt = lambda ds: sum((Decimal(str(d.get('amount') or 0)) for d in ds), ZERO)
    st = stages(config)
    soft_floor = 'soft committed' if 'soft committed' in st else st[len(st) // 2]
    signed_floor = 'signed' if 'signed' in st else st[-2]
    received = st[-1]
    out = {
        'target': Decimal(str(round_.get('target') or 0)),
        'soft': amt([d for d in mine if at_least(d.get('stage'), soft_floor, config)]),
        'signed': amt([d for d in mine if at_least(d.get('stage'), signed_floor, config)]),
        'received': amt([d for d in mine if d.get('stage') == received]),
        'investors': len([d for d in mine if d.get('stage') != CLOSED_LOST]),
        'passed': len([d for d in mine if d.get('stage') == CLOSED_LOST]),
    }
    out['remaining'] = max(ZERO, out['target'] - out['soft'])
    return out


def momentum(deals, config=None):
    """Monthly counts: {'investor_connections': {YYYY-MM: n}, 'investor_meetings': ..., 'investors_converted': ...}."""
    out = {'investor_connections': {}, 'investor_meetings': {}, 'investors_converted': {}}

    def bump(key, d):
        if d:
            m = str(d)[:7]
            out[key][m] = out[key].get(m, ZERO) + 1

    signed_floor = 'signed' if 'signed' in stages(config) else stages(config)[-2]
    for deal in deals:
        bump('investor_connections', deal.get('first_meeting') or deal.get('created'))
        if deal.get('first_meeting'):
            bump('investor_meetings', deal['first_meeting'])
        for n in deal.get('notes') or []:
            if n.get('meeting'):
                bump('investor_meetings', n.get('date'))
        reached = [h for h in deal.get('history') or [] if at_least(h.get('stage'), signed_floor, config)]
        if reached:
            bump('investors_converted', sorted(h['date'] for h in reached)[0])
    return out


def set_stage(deal, stage, on=None, config=None):
    if stage not in stages(config) + [CLOSED_LOST]:
        raise ValueError(f"stage must be one of: {', '.join(stages(config) + [CLOSED_LOST])}")
    on = on or date.today().isoformat()
    if deal.get('stage') != stage:
        deal.setdefault('history', []).append({'date': on, 'stage': stage})
    deal['stage'] = stage
    deal['last_meeting'] = deal.get('last_meeting') or deal.get('first_meeting')
    return deal


def funding_entry(deal, round_, bank, currency, on):
    """(postings, tags, description) for money received from a deal."""
    instrument = round_.get('instrument', 'equity')
    account, pair = FUNDING_ACCOUNTS.get(instrument, FUNDING_ACCOUNTS['equity'])
    amount = float(Decimal(str(deal.get('amount') or 0)))
    if amount <= 0:
        raise ValueError("The commitment has no amount")
    postings = [(bank, currency, amount), (account, currency, -amount)]
    tags = build_tags(pair, funding=instrument, round=round_['id'], investor=deal['id'])
    desc = f"{round_.get('name', round_['id'])} — {deal.get('investor', deal['id'])}"
    return postings, tags, desc


def captable_step(deal, round_, on):
    """The cap-table change for money received: an issuance or an instrument."""
    instrument = round_.get('instrument', 'equity')
    amount = Decimal(str(deal.get('amount') or 0))
    if instrument in ('safe', 'note'):
        return {'type': instrument, 'holder': deal['id'], 'holder_name': deal.get('investor'),
                'amount': amount, 'date': on, 'cap': round_.get('cap'), 'discount': round_.get('discount'),
                'interest': round_.get('interest'),
                'post_money': round_.get('post_money', instrument == 'safe')}
    if instrument == 'equity':
        price = Decimal(str(round_.get('price') or 0))
        if not price:
            return None
        cls = round_.get('class') or round_['id']
        return {'type': 'issue', 'holder': deal['id'], 'holder_name': deal.get('investor'),
                'class': cls, 'class_name': f"{round_.get('name', cls)} Preferred",
                'shares': amount / price, 'price': price, 'date': on}
    return None
