"""Company profile — who the company is, kept in the entity's config.yaml.

    profile:
      status: real            # real | speculative (an idea or a company not yet formed)
      one_liner: ...
      stage: pre-seed
      ...
      founders: [Name, Name]
      links: [{label: Pitch deck, url: https://...}]
"""

FIELDS = [
    # key, label, kind, help
    ('status', 'Status', 'choice:real,speculative', 'Speculative = an idea or a company not formed yet'),
    ('one_liner', 'One-liner', 'text', 'What the company does, in one sentence'),
    ('stage', 'Stage', 'choice:idea,pre-seed,seed,series-a,series-b,growth,mature', ''),
    ('business_type', 'Business type', 'text', 'e.g. CCPC, Delaware C Corp, sole proprietorship'),
    ('industry', 'Industry', 'text', ''),
    ('founded', 'Founding year', 'number', ''),
    ('team_size', 'Team size', 'number', ''),
    ('location', 'Location', 'text', ''),
    ('website', 'Website', 'text', ''),
    ('founders', 'Founders', 'list', 'Comma-separated names'),
    ('tam', 'Total addressable market', 'money', 'Whole market size'),
    ('market_share_5y', 'Market share in 5 years', 'percent', 'As a fraction (0.02 = 2%)'),
    ('exit_multiple', 'Industry exit multiple', 'number', 'Typical revenue multiple at exit'),
    ('plan_scenario', 'Plan scenario', 'text', 'Scenario slug the Overview uses for runway and plan'),
    ('notes', 'Notes', 'text', ''),
]
KEYS = {k for k, *_ in FIELDS}


def load(config):
    p = dict((config or {}).get('profile') or {})
    p.setdefault('status', 'real')
    p.setdefault('links', [])
    return p


def coerce(key, value):
    """Turn input text into the stored value for a field (ValueError if bad)."""
    kind = next(k for f, _, k, _ in FIELDS if f == key)
    if value in (None, ''):
        return None
    if kind.startswith('choice:'):
        options = kind[7:].split(',')
        if value not in options:
            raise ValueError(f"{key} must be one of {', '.join(options)}")
        return value
    if kind == 'list':
        return [v.strip() for v in value.split(',') if v.strip()] if isinstance(value, str) else list(value)
    if kind in ('number', 'money', 'percent'):
        n = float(value)
        if kind == 'percent' and not 0 <= n <= 1:
            raise ValueError(f"{key} is a fraction between 0 and 1 (0.02 = 2%)")
        return int(n) if kind == 'number' and n == int(n) else n
    return str(value)


def update(config, changes):
    """Apply {key: value} to config['profile'] (None removes); returns the profile."""
    profile = dict(config.get('profile') or {})
    for key, value in changes.items():
        if key == 'links':
            profile['links'] = [{'label': str(l.get('label', '')).strip(), 'url': str(l.get('url', '')).strip()}
                                for l in (value or []) if l.get('url')]
            continue
        if key not in KEYS:
            raise ValueError(f"Unknown profile field: {key}")
        v = coerce(key, value)
        if v is None:
            profile.pop(key, None)
        else:
            profile[key] = v
    config['profile'] = profile
    return load(config)
