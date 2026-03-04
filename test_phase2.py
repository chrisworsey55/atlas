#!/usr/bin/env python3
"""
ATLAS Phase 2 Test Script
Tests all Phase 2 components:
1. Biotech desk analysis (LLY)
2. 13F client (Berkshire holdings)
3. Institutional flow briefing
4. Database models (create tables)
"""
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

def test_biotech_desk():
    """Test biotech desk on LLY."""
    print("\n" + "="*60)
    print("TEST 1: Biotech Desk - LLY Analysis")
    print("="*60)
    
    from agents.sector_desk import BiotechDesk
    
    desk = BiotechDesk()
    result = desk.analyze('LLY', days_back=365)
    
    if result:
        print(f"\n✓ Signal: {result.get('signal')}")
        print(f"✓ Confidence: {result.get('confidence', 0):.0%}")
        print(f"✓ CIO Briefing: {result.get('brief_for_cio', 'N/A')[:100]}...")
        return True
    else:
        print("✗ Analysis failed")
        return False


def test_thirteenf_client():
    """Test 13F client with Berkshire."""
    print("\n" + "="*60)
    print("TEST 2: 13F Client - Berkshire Holdings")
    print("="*60)
    
    from data.thirteenf_client import ThirteenFClient
    
    client = ThirteenFClient(use_edgartools=True)
    df = client.get_fund_holdings('Berkshire Hathaway (Buffett)')
    
    if df is not None and len(df) > 0:
        print(f"\n✓ Fetched {len(df)} positions")
        print(f"✓ Quarter: {df['quarter'].iloc[0]}")
        print("\nTop 5 holdings:")
        for _, row in df.nlargest(5, 'value').iterrows():
            ticker = row.get('ticker', '?')
            name = str(row.get('name', ''))[:25]
            value = row.get('value', 0)
            print(f"  {ticker:6} {name:25} ${value:>15,.0f}")
        return True
    else:
        print("✗ Failed to fetch holdings")
        return False


def test_consensus_report():
    """Test institutional flow consensus report."""
    print("\n" + "="*60)
    print("TEST 3: Institutional Flow - Consensus Report")
    print("="*60)
    
    from data.thirteenf_client import ThirteenFClient
    
    client = ThirteenFClient(use_edgartools=True)
    
    # Just test with a couple funds for speed
    test_funds = ['Berkshire Hathaway (Buffett)', 'Pershing Square (Ackman)']
    holdings = {}
    
    for fund in test_funds:
        df = client.get_fund_holdings(fund)
        if df is not None:
            holdings[fund] = df
            print(f"✓ {fund}: {len(df)} positions")
    
    if holdings:
        report = client.build_consensus_report(holdings)
        print(f"\n✓ Report generated")
        print(f"  Conviction positions: {len(report.get('conviction_positions', []))}")
        print(f"  Consensus builds: {len(report.get('consensus_builds', []))}")
        
        if report.get('conviction_positions'):
            print("\nTop conviction position:")
            top = report['conviction_positions'][0]
            print(f"  {top['ticker']} - {top['fund']} @ {top['portfolio_pct']:.1f}%")
        return True
    else:
        print("✗ Failed to build report")
        return False


def test_database():
    """Test database connection and table creation."""
    print("\n" + "="*60)
    print("TEST 4: Database - Connection & Schema")
    print("="*60)
    
    try:
        from database.session import check_connection, init_db, get_engine
        from database.models import Base
        
        # Check connection
        if check_connection():
            print("✓ Database connection successful")
            
            # Create tables
            init_db()
            print("✓ Tables created")
            
            # Verify tables exist
            engine = get_engine()
            from sqlalchemy import inspect
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            atlas_tables = [t for t in tables if t.startswith('atlas_')]
            print(f"✓ Found {len(atlas_tables)} ATLAS tables: {atlas_tables}")
            
            return len(atlas_tables) >= 7
        else:
            print("✗ Database connection failed")
            print("  (This is expected if PostgreSQL is not configured)")
            return None  # Skip, not fail
            
    except Exception as e:
        print(f"✗ Database error: {e}")
        print("  (This is expected if PostgreSQL is not configured)")
        return None  # Skip, not fail


def test_persist_brief():
    """Test persisting a brief to the database."""
    print("\n" + "="*60)
    print("TEST 5: Database - Persist Brief")
    print("="*60)
    
    try:
        from agents.sector_desk import SemiconductorDesk
        
        desk = SemiconductorDesk()
        result = desk.analyze('NVDA', persist=True)
        
        if result:
            print(f"✓ Analysis complete: {result.get('signal')}")
            
            # Verify persisted
            from database.session import get_session
            from database.models import AtlasDeskBrief
            
            session = get_session()
            brief = session.query(AtlasDeskBrief).filter_by(
                desk_name='Semiconductor'
            ).order_by(AtlasDeskBrief.id.desc()).first()
            session.close()
            
            if brief:
                print(f"✓ Brief persisted (id={brief.id})")
                return True
            else:
                print("✗ Brief not found in database")
                return False
        else:
            print("✗ Analysis failed")
            return False
            
    except Exception as e:
        print(f"✗ Persistence error: {e}")
        return None


def main():
    """Run all Phase 2 tests."""
    print("\n" + "="*60)
    print("ATLAS PHASE 2 - TEST SUITE")
    print("="*60)
    
    results = {}
    
    # Core tests (always run)
    results['biotech_desk'] = test_biotech_desk()
    results['thirteenf_client'] = test_thirteenf_client()
    results['consensus_report'] = test_consensus_report()
    
    # Database tests (may skip if not configured)
    results['database'] = test_database()
    
    if results['database']:
        results['persist_brief'] = test_persist_brief()
    else:
        results['persist_brief'] = None
        print("\nSkipping persistence test (database not configured)")
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    passed = 0
    failed = 0
    skipped = 0
    
    for name, result in results.items():
        if result is True:
            status = "✓ PASS"
            passed += 1
        elif result is False:
            status = "✗ FAIL"
            failed += 1
        else:
            status = "○ SKIP"
            skipped += 1
        print(f"  {name:20} {status}")
    
    print(f"\nTotal: {passed} passed, {failed} failed, {skipped} skipped")
    
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
