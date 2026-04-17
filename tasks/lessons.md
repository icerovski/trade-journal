# Pattern: Inception Risk Anchor
- Permanent 'Risk Anchor' stored during initial profile creation.
- Managed via set_position_risk with conditional update (NULL check).
- Propagated from WATCH to ACTIVE status to preserve audit trail.
- Displayed in Audit UI to measure trailing distance.
