"""Initial ATLAS schema

Revision ID: 001_initial
Revises: 
Create Date: 2026-03-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # atlas_companies
    op.create_table(
        'atlas_companies',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ticker', sa.String(10), nullable=False),
        sa.Column('cik', sa.String(10), nullable=True),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('sector', sa.String(100), nullable=True),
        sa.Column('industry', sa.String(100), nullable=True),
        sa.Column('market_cap', sa.Float(), nullable=True),
        sa.Column('in_universe', sa.Boolean(), default=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ticker')
    )
    op.create_index('ix_atlas_companies_ticker', 'atlas_companies', ['ticker'])
    op.create_index('ix_atlas_companies_cik', 'atlas_companies', ['cik'])
    op.create_index('ix_atlas_companies_sector', 'atlas_companies', ['sector'])
    op.create_index('ix_atlas_companies_sector_universe', 'atlas_companies', ['sector', 'in_universe'])
    
    # atlas_filings
    op.create_table(
        'atlas_filings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('filing_type', sa.String(20), nullable=False),
        sa.Column('accession_number', sa.String(25), nullable=True),
        sa.Column('filed_date', sa.Date(), nullable=False),
        sa.Column('period_end_date', sa.Date(), nullable=True),
        sa.Column('raw_text_path', sa.String(500), nullable=True),
        sa.Column('extracted_json', postgresql.JSON(), nullable=True),
        sa.Column('processed', sa.Boolean(), default=False),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['atlas_companies.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('accession_number')
    )
    op.create_index('ix_atlas_filings_company_id', 'atlas_filings', ['company_id'])
    op.create_index('ix_atlas_filings_filed_date', 'atlas_filings', ['filed_date'])
    op.create_index('ix_atlas_filings_company_date', 'atlas_filings', ['company_id', 'filed_date'])
    
    # atlas_desk_briefs
    op.create_table(
        'atlas_desk_briefs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('desk_name', sa.String(50), nullable=False),
        sa.Column('analysis_date', sa.Date(), nullable=False),
        sa.Column('brief_json', postgresql.JSON(), nullable=False),
        sa.Column('signal_direction', sa.String(20), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('filing_id', sa.Integer(), nullable=True),
        sa.Column('filing_type', sa.String(20), nullable=True),
        sa.Column('filing_date', sa.Date(), nullable=True),
        sa.Column('cio_briefing', sa.Text(), nullable=True),
        sa.Column('bull_case', sa.Text(), nullable=True),
        sa.Column('bear_case', sa.Text(), nullable=True),
        sa.Column('model_used', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['atlas_companies.id']),
        sa.ForeignKeyConstraint(['filing_id'], ['atlas_filings.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'desk_name', 'analysis_date', name='uq_brief_per_day')
    )
    op.create_index('ix_atlas_desk_briefs_company_id', 'atlas_desk_briefs', ['company_id'])
    op.create_index('ix_atlas_desk_briefs_desk_name', 'atlas_desk_briefs', ['desk_name'])
    op.create_index('ix_atlas_desk_briefs_analysis_date', 'atlas_desk_briefs', ['analysis_date'])
    op.create_index('ix_atlas_briefs_desk_date', 'atlas_desk_briefs', ['desk_name', 'analysis_date'])
    op.create_index('ix_atlas_briefs_signal_confidence', 'atlas_desk_briefs', ['signal_direction', 'confidence'])
    
    # atlas_institutional_holdings
    op.create_table(
        'atlas_institutional_holdings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('fund_name', sa.String(100), nullable=False),
        sa.Column('fund_cik', sa.String(10), nullable=True),
        sa.Column('ticker', sa.String(10), nullable=True),
        sa.Column('cusip', sa.String(9), nullable=True),
        sa.Column('company_name', sa.String(255), nullable=True),
        sa.Column('shares', sa.Float(), nullable=True),
        sa.Column('value', sa.Float(), nullable=True),
        sa.Column('quarter', sa.String(7), nullable=False),
        sa.Column('filing_date', sa.Date(), nullable=True),
        sa.Column('change_type', sa.String(20), nullable=True),
        sa.Column('change_pct', sa.Float(), nullable=True),
        sa.Column('portfolio_pct', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('fund_name', 'cusip', 'quarter', name='uq_holding_per_quarter')
    )
    op.create_index('ix_atlas_holdings_fund_name', 'atlas_institutional_holdings', ['fund_name'])
    op.create_index('ix_atlas_holdings_ticker', 'atlas_institutional_holdings', ['ticker'])
    op.create_index('ix_atlas_holdings_quarter', 'atlas_institutional_holdings', ['quarter'])
    op.create_index('ix_atlas_holdings_fund_quarter', 'atlas_institutional_holdings', ['fund_name', 'quarter'])
    op.create_index('ix_atlas_holdings_ticker_quarter', 'atlas_institutional_holdings', ['ticker', 'quarter'])
    
    # atlas_theses
    op.create_table(
        'atlas_theses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('direction', sa.String(10), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('bull_case', sa.Text(), nullable=True),
        sa.Column('bear_case', sa.Text(), nullable=True),
        sa.Column('catalyst', sa.Text(), nullable=True),
        sa.Column('timeframe', sa.String(50), nullable=True),
        sa.Column('invalidation_criteria', sa.Text(), nullable=True),
        sa.Column('stop_loss_pct', sa.Float(), nullable=True),
        sa.Column('target_return_pct', sa.Float(), nullable=True),
        sa.Column('max_position_size_pct', sa.Float(), nullable=True),
        sa.Column('status', sa.String(20), default='ACTIVE'),
        sa.Column('status_reason', sa.Text(), nullable=True),
        sa.Column('source_brief_ids', postgresql.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['atlas_companies.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_atlas_theses_company_id', 'atlas_theses', ['company_id'])
    op.create_index('ix_atlas_theses_status', 'atlas_theses', ['status'])
    op.create_index('ix_atlas_theses_status_date', 'atlas_theses', ['status', 'created_at'])
    
    # atlas_trades
    op.create_table(
        'atlas_trades',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('thesis_id', sa.Integer(), nullable=False),
        sa.Column('ticker', sa.String(10), nullable=False),
        sa.Column('direction', sa.String(10), nullable=False),
        sa.Column('shares', sa.Float(), nullable=False),
        sa.Column('entry_price', sa.Float(), nullable=False),
        sa.Column('entry_date', sa.DateTime(), nullable=False),
        sa.Column('entry_rationale', sa.Text(), nullable=True),
        sa.Column('exit_price', sa.Float(), nullable=True),
        sa.Column('exit_date', sa.DateTime(), nullable=True),
        sa.Column('exit_rationale', sa.Text(), nullable=True),
        sa.Column('pnl_dollars', sa.Float(), nullable=True),
        sa.Column('pnl_pct', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['thesis_id'], ['atlas_theses.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_atlas_trades_thesis_id', 'atlas_trades', ['thesis_id'])
    op.create_index('ix_atlas_trades_ticker', 'atlas_trades', ['ticker'])
    op.create_index('ix_atlas_trades_entry_date', 'atlas_trades', ['entry_date'])
    op.create_index('ix_atlas_trades_ticker_date', 'atlas_trades', ['ticker', 'entry_date'])
    
    # atlas_portfolio_snapshots
    op.create_table(
        'atlas_portfolio_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('total_value', sa.Float(), nullable=False),
        sa.Column('cash', sa.Float(), nullable=False),
        sa.Column('long_exposure', sa.Float(), nullable=True),
        sa.Column('short_exposure', sa.Float(), nullable=True),
        sa.Column('net_exposure', sa.Float(), nullable=True),
        sa.Column('gross_exposure', sa.Float(), nullable=True),
        sa.Column('positions_json', postgresql.JSON(), nullable=True),
        sa.Column('num_positions', sa.Integer(), nullable=True),
        sa.Column('daily_return', sa.Float(), nullable=True),
        sa.Column('cumulative_return', sa.Float(), nullable=True),
        sa.Column('max_drawdown', sa.Float(), nullable=True),
        sa.Column('sharpe_ratio', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('date')
    )
    op.create_index('ix_atlas_portfolio_snapshots_date', 'atlas_portfolio_snapshots', ['date'])


def downgrade() -> None:
    op.drop_table('atlas_portfolio_snapshots')
    op.drop_table('atlas_trades')
    op.drop_table('atlas_theses')
    op.drop_table('atlas_institutional_holdings')
    op.drop_table('atlas_desk_briefs')
    op.drop_table('atlas_filings')
    op.drop_table('atlas_companies')
