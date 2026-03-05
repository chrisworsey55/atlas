"""
Premium Data Stubs for ATLAS
Placeholder classes for paid data sources to be implemented when AUM hits $50M.

TIER 2 — PAID BUT WORTH IT

These premium data sources provide significant alpha but require subscriptions:
1. Credit card transaction data (Second Measure, Earnest Research)
2. Web traffic data (SimilarWeb, Semrush)
3. App download/usage data (Sensor Tower, Apptopia)
4. Satellite imagery (Orbital Insight, RS Metrics)
5. Geolocation / foot traffic (Placer.ai, SafeGraph)
6. Job posting data (Revelio Labs, Thinknum)
7. Patent filings (Google Patents, PatSnap)
8. Supply chain data (Panjiva, ImportGenius)
9. Expert network transcripts (Tegus, AlphaSights)

Architecture is ready - when we subscribe, just fill in the API calls.
"""
import logging
from datetime import datetime
from typing import Optional
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class PremiumDataClient(ABC):
    """Abstract base class for premium data clients."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key
        self._is_configured = api_key is not None

    @property
    def is_available(self) -> bool:
        """Check if this premium data source is configured."""
        return self._is_configured

    def _not_configured_error(self, method_name: str) -> dict:
        """Return standard error for unconfigured premium sources."""
        return {
            "error": "Premium data source not configured",
            "source": self.__class__.__name__,
            "method": method_name,
            "message": f"Subscribe to {self.__class__.__name__} and set API key to enable",
        }


class CreditCardDataClient(PremiumDataClient):
    """
    Credit card transaction data (Second Measure, Earnest Research).
    See consumer spending at portfolio companies before earnings.

    Providers:
    - Second Measure: https://secondmeasure.com
    - Earnest Research: https://www.earnestresearch.com
    """

    PROVIDERS = ["Second Measure", "Earnest Research"]

    def get_spending_trends(self, ticker: str, days: int = 90) -> dict:
        """
        Get consumer spending trends for a company.

        Args:
            ticker: Stock ticker symbol
            days: Days of history

        Returns:
            Dict with spending trend data (YoY growth, MoM growth, market share)
        """
        if not self.is_available:
            return self._not_configured_error("get_spending_trends")

        # TODO: Implement when subscribed
        # Expected return format:
        # {
        #     "ticker": ticker,
        #     "yoy_growth": 15.2,  # Year-over-year spending growth %
        #     "mom_growth": 2.1,   # Month-over-month growth %
        #     "market_share": 23.5, # Share of category spending
        #     "trend": "ACCELERATING",  # ACCELERATING, STABLE, DECELERATING
        #     "vs_sector": 1.5,  # Multiple vs sector average
        # }
        raise NotImplementedError("Credit card data requires subscription")

    def get_category_share(self, ticker: str, category: str) -> dict:
        """Get company's share of spending in a category."""
        if not self.is_available:
            return self._not_configured_error("get_category_share")
        raise NotImplementedError("Credit card data requires subscription")


class WebTrafficClient(PremiumDataClient):
    """
    Web traffic data (SimilarWeb, Semrush).
    Track website visits as a revenue proxy.

    Providers:
    - SimilarWeb: https://www.similarweb.com
    - Semrush: https://www.semrush.com
    """

    PROVIDERS = ["SimilarWeb", "Semrush"]

    def get_traffic_trends(self, domain: str, months: int = 6) -> dict:
        """
        Get website traffic trends.

        Args:
            domain: Company website domain
            months: Months of history

        Returns:
            Dict with traffic metrics (visits, unique visitors, bounce rate, etc.)
        """
        if not self.is_available:
            return self._not_configured_error("get_traffic_trends")

        # TODO: Implement when subscribed
        # Expected return format:
        # {
        #     "domain": domain,
        #     "monthly_visits": 50_000_000,
        #     "unique_visitors": 30_000_000,
        #     "yoy_growth": 12.5,
        #     "mom_growth": 1.2,
        #     "avg_visit_duration": 180,  # seconds
        #     "bounce_rate": 45.2,
        #     "pages_per_visit": 3.5,
        # }
        raise NotImplementedError("Web traffic data requires subscription")

    def get_competitor_comparison(self, domains: list) -> dict:
        """Compare traffic across competitor domains."""
        if not self.is_available:
            return self._not_configured_error("get_competitor_comparison")
        raise NotImplementedError("Web traffic data requires subscription")


class AppDataClient(PremiumDataClient):
    """
    App download/usage data (Sensor Tower, Apptopia).
    Track mobile app engagement.

    Providers:
    - Sensor Tower: https://sensortower.com
    - Apptopia: https://apptopia.com
    """

    PROVIDERS = ["Sensor Tower", "Apptopia"]

    def get_app_metrics(self, app_name: str) -> dict:
        """
        Get app download and usage metrics.

        Args:
            app_name: App name or ID

        Returns:
            Dict with app metrics (downloads, DAU, MAU, retention, etc.)
        """
        if not self.is_available:
            return self._not_configured_error("get_app_metrics")

        # TODO: Implement when subscribed
        # Expected return format:
        # {
        #     "app_name": app_name,
        #     "downloads_monthly": 5_000_000,
        #     "downloads_yoy": 25.0,
        #     "dau": 2_000_000,  # Daily active users
        #     "mau": 15_000_000, # Monthly active users
        #     "dau_mau_ratio": 0.13,  # Stickiness
        #     "retention_d1": 40.0,  # Day 1 retention
        #     "retention_d7": 25.0,
        #     "retention_d30": 15.0,
        #     "app_store_rating": 4.5,
        #     "ranking_category": 5,
        # }
        raise NotImplementedError("App data requires subscription")

    def get_app_store_rankings(self, category: str, country: str = "US") -> list:
        """Get app store rankings for a category."""
        if not self.is_available:
            return self._not_configured_error("get_app_store_rankings")
        raise NotImplementedError("App data requires subscription")


class SatelliteDataClient(PremiumDataClient):
    """
    Satellite imagery analysis (Orbital Insight, RS Metrics).
    Track parking lot counts, oil storage levels, shipping activity.

    Providers:
    - Orbital Insight: https://orbitalinsight.com
    - RS Metrics: https://www.rsmetrics.com
    """

    PROVIDERS = ["Orbital Insight", "RS Metrics"]

    def get_parking_lot_counts(self, ticker: str, location_type: str = "all") -> dict:
        """
        Get parking lot car counts for retail locations.

        Args:
            ticker: Retail company ticker
            location_type: "all", "stores", "distribution"

        Returns:
            Dict with parking lot traffic data
        """
        if not self.is_available:
            return self._not_configured_error("get_parking_lot_counts")

        # TODO: Implement when subscribed
        # Expected return format:
        # {
        #     "ticker": ticker,
        #     "avg_cars_per_location": 150,
        #     "yoy_change": 5.2,
        #     "wow_change": 1.5,  # Week over week
        #     "vs_historical_avg": 1.05,
        #     "locations_analyzed": 500,
        # }
        raise NotImplementedError("Satellite data requires subscription")

    def get_oil_storage_levels(self, region: str = "cushing") -> dict:
        """Get crude oil storage tank fill levels."""
        if not self.is_available:
            return self._not_configured_error("get_oil_storage_levels")
        raise NotImplementedError("Satellite data requires subscription")

    def get_shipping_activity(self, port: str) -> dict:
        """Get shipping container activity at major ports."""
        if not self.is_available:
            return self._not_configured_error("get_shipping_activity")
        raise NotImplementedError("Satellite data requires subscription")


class FootTrafficClient(PremiumDataClient):
    """
    Geolocation / foot traffic data (Placer.ai, SafeGraph).
    Track retail store visits.

    Providers:
    - Placer.ai: https://www.placer.ai
    - SafeGraph: https://www.safegraph.com
    """

    PROVIDERS = ["Placer.ai", "SafeGraph"]

    def get_store_visits(self, ticker: str, days: int = 30) -> dict:
        """
        Get foot traffic to retail stores.

        Args:
            ticker: Retail company ticker
            days: Days of data

        Returns:
            Dict with foot traffic metrics
        """
        if not self.is_available:
            return self._not_configured_error("get_store_visits")

        # TODO: Implement when subscribed
        # Expected return format:
        # {
        #     "ticker": ticker,
        #     "total_visits": 10_000_000,
        #     "yoy_change": 8.5,
        #     "wow_change": 2.1,
        #     "avg_dwell_time": 25,  # minutes
        #     "new_vs_returning": 0.35,
        #     "cross_shopping": ["TGT", "WMT"],  # Where else visitors shop
        # }
        raise NotImplementedError("Foot traffic data requires subscription")

    def get_location_comparison(self, tickers: list) -> dict:
        """Compare foot traffic across competing retailers."""
        if not self.is_available:
            return self._not_configured_error("get_location_comparison")
        raise NotImplementedError("Foot traffic data requires subscription")


class JobPostingClient(PremiumDataClient):
    """
    Job posting data (Revelio Labs, Thinknum).
    Hiring acceleration = growth signal, hiring freeze = warning.

    Providers:
    - Revelio Labs: https://www.reveliolabs.com
    - Thinknum: https://www.thinknum.com
    """

    PROVIDERS = ["Revelio Labs", "Thinknum"]

    def get_hiring_trends(self, ticker: str, months: int = 6) -> dict:
        """
        Get job posting and hiring trends.

        Args:
            ticker: Company ticker
            months: Months of history

        Returns:
            Dict with hiring metrics
        """
        if not self.is_available:
            return self._not_configured_error("get_hiring_trends")

        # TODO: Implement when subscribed
        # Expected return format:
        # {
        #     "ticker": ticker,
        #     "active_job_postings": 500,
        #     "mom_change": 15.0,
        #     "yoy_change": 45.0,
        #     "engineering_openings": 150,
        #     "sales_openings": 100,
        #     "hiring_velocity": "ACCELERATING",  # ACCELERATING, STABLE, DECELERATING, FREEZING
        #     "avg_time_to_fill": 30,  # days
        #     "glassdoor_rating": 4.2,
        # }
        raise NotImplementedError("Job posting data requires subscription")

    def get_employee_count_trends(self, ticker: str) -> dict:
        """Get LinkedIn employee count trends."""
        if not self.is_available:
            return self._not_configured_error("get_employee_count_trends")
        raise NotImplementedError("Job posting data requires subscription")


class PatentDataClient(PremiumDataClient):
    """
    Patent filing data (Google Patents, PatSnap).
    R&D pipeline signals.

    Providers:
    - PatSnap: https://www.patsnap.com
    - Google Patents (partially free): https://patents.google.com
    """

    PROVIDERS = ["PatSnap", "Google Patents"]

    def get_patent_filings(self, ticker: str, years: int = 2) -> dict:
        """
        Get patent filing activity.

        Args:
            ticker: Company ticker
            years: Years of history

        Returns:
            Dict with patent metrics
        """
        if not self.is_available:
            return self._not_configured_error("get_patent_filings")

        # TODO: Implement when subscribed
        # Expected return format:
        # {
        #     "ticker": ticker,
        #     "total_patents": 5000,
        #     "filings_ytd": 250,
        #     "yoy_change": 15.0,
        #     "top_categories": ["AI/ML", "Cloud Computing", "Hardware"],
        #     "citations_received": 10000,
        #     "patent_quality_score": 85,
        #     "r_and_d_intensity": "HIGH",
        # }
        raise NotImplementedError("Patent data requires subscription")

    def get_patent_landscape(self, technology: str) -> dict:
        """Get patent landscape for a technology area."""
        if not self.is_available:
            return self._not_configured_error("get_patent_landscape")
        raise NotImplementedError("Patent data requires subscription")


class SupplyChainClient(PremiumDataClient):
    """
    Supply chain data (Panjiva, ImportGenius).
    Shipping and import/export signals.

    Providers:
    - Panjiva: https://panjiva.com
    - ImportGenius: https://www.importgenius.com
    """

    PROVIDERS = ["Panjiva", "ImportGenius"]

    def get_import_activity(self, ticker: str, months: int = 6) -> dict:
        """
        Get import shipment activity.

        Args:
            ticker: Company ticker
            months: Months of history

        Returns:
            Dict with import metrics
        """
        if not self.is_available:
            return self._not_configured_error("get_import_activity")

        # TODO: Implement when subscribed
        # Expected return format:
        # {
        #     "ticker": ticker,
        #     "shipments_month": 500,
        #     "yoy_change": 20.0,
        #     "mom_change": 5.0,
        #     "top_origins": ["China", "Vietnam", "Mexico"],
        #     "container_volume": 2000,  # TEUs
        #     "avg_lead_time": 45,  # days
        # }
        raise NotImplementedError("Supply chain data requires subscription")

    def get_supplier_network(self, ticker: str) -> dict:
        """Map company's supplier network."""
        if not self.is_available:
            return self._not_configured_error("get_supplier_network")
        raise NotImplementedError("Supply chain data requires subscription")


class ExpertNetworkClient(PremiumDataClient):
    """
    Expert network transcripts (Tegus, AlphaSights).
    Primary research from industry experts.

    Providers:
    - Tegus: https://www.tegus.com
    - AlphaSights: https://www.alphasights.com
    """

    PROVIDERS = ["Tegus", "AlphaSights"]

    def get_expert_transcripts(self, ticker: str, limit: int = 10) -> list:
        """
        Get recent expert call transcripts.

        Args:
            ticker: Company ticker
            limit: Maximum transcripts to return

        Returns:
            List of transcript summaries
        """
        if not self.is_available:
            return self._not_configured_error("get_expert_transcripts")

        # TODO: Implement when subscribed
        # Expected return format:
        # [{
        #     "date": "2025-01-15",
        #     "expert_title": "Former VP Engineering",
        #     "topic": "AI Infrastructure Roadmap",
        #     "key_insights": ["..."],
        #     "sentiment": "POSITIVE",
        #     "relevance_score": 85,
        # }]
        raise NotImplementedError("Expert network data requires subscription")

    def search_transcripts(self, query: str, tickers: list = None) -> list:
        """Search expert transcripts by topic."""
        if not self.is_available:
            return self._not_configured_error("search_transcripts")
        raise NotImplementedError("Expert network data requires subscription")


# Factory function to get premium clients
def get_premium_clients() -> dict:
    """
    Get all premium data clients.
    Each will report whether it's configured.
    """
    return {
        "credit_card": CreditCardDataClient(),
        "web_traffic": WebTrafficClient(),
        "app_data": AppDataClient(),
        "satellite": SatelliteDataClient(),
        "foot_traffic": FootTrafficClient(),
        "job_posting": JobPostingClient(),
        "patent": PatentDataClient(),
        "supply_chain": SupplyChainClient(),
        "expert_network": ExpertNetworkClient(),
    }


def get_premium_status() -> dict:
    """Get configuration status of all premium data sources."""
    clients = get_premium_clients()
    return {
        name: {
            "is_available": client.is_available,
            "providers": client.PROVIDERS if hasattr(client, "PROVIDERS") else [],
        }
        for name, client in clients.items()
    }


if __name__ == "__main__":
    print("\n" + "="*60)
    print("ATLAS Premium Data Stubs")
    print("="*60 + "\n")

    status = get_premium_status()

    print("Premium Data Source Status:\n")
    for name, info in status.items():
        available = "CONFIGURED" if info["is_available"] else "NOT CONFIGURED"
        providers = ", ".join(info["providers"])
        print(f"  {name}:")
        print(f"    Status: {available}")
        print(f"    Providers: {providers}")
        print()

    print("\nNote: Configure API keys in settings.py when AUM hits $50M")
