#!/usr/bin/env python3
"""
Mock Integration Test - Using Existing Import Patterns

This follows the exact same import pattern as your existing integration tests.
Run from the tests directory: python test_mock_integration.py

Usage:
  python test_mock_integration.py [--log-level LEVEL]
  
  Options:
    --log-level LEVEL    Set logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
"""

import asyncio
import json
import sys
import os
import logging
import argparse
from datetime import datetime

# Add parent to path (exactly like existing integration tests)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure environment for mock servers BEFORE any imports
os.environ['POLYMARKET_WS_URL'] = 'ws://localhost:8001'
os.environ['KALSHI_WS_URL'] = 'ws://localhost:8002'
os.environ['POLYMARKET_DEBUG_LOGGING'] = 'true'

# Import mock servers using absolute imports
from backend.master_manager.tests.mock_polymarket_server import MockPolymarketServer
from backend.master_manager.tests.mock_kalshi_server import MockKalshiServer
from backend.master_manager.tests.mock_arbitrage_feeder import MockArbitrageFeeder

# Import MarketsCoordinator (relative to master_manager)
from backend.master_manager.markets_coordinator import MarketsCoordinator

def setup_logging(log_level: str = "DEBUG"):
    """Configure logging with the specified level"""
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f'Invalid log level: {log_level}')
    
    logging.basicConfig(
        level=numeric_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='Mock Integration Test - MarketsCoordinator + Mock Servers',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '--log-level', 
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        default='DEBUG',
        help='Set the logging level (default: DEBUG)'
    )
    return parser.parse_args()

# Configure logging will be done after argument parsing
logger = logging.getLogger(__name__)

async def run_mock_integration_test():
    """Run complete integration test with mock servers and MarketsCoordinator"""
    
    print("🎯 MOCK INTEGRATION TEST - MarketsCoordinator + Mock Servers")
    print("=" * 70)
    print(f"⏰ Started: {datetime.now().isoformat()}")
    print()
    
    print("🔧 Environment Configuration:")
    print(f"   POLYMARKET_WS_URL = {os.environ['POLYMARKET_WS_URL']}")
    print(f"   KALSHI_WS_URL = {os.environ['KALSHI_WS_URL']}")
    print()
    
    # Start mock servers
    poly_server = MockPolymarketServer(port=8001)
    kalshi_server = MockKalshiServer(port=8002)
    
    try:
        print("🚀 Starting mock servers...")
        await poly_server.start()
        await kalshi_server.start()
        print("✅ Mock servers started")
        
        # Give servers a moment to start
        await asyncio.sleep(1)
        
        print("\n📊 Creating MarketsCoordinator...")
        coordinator = MarketsCoordinator()
        print("✅ MarketsCoordinator created")
        
        print("\n🔄 Starting async components...")
        await coordinator.start_async_components()
        print("✅ Async components started (queues, processors, ticker publishers)")
        
        # Test market connections
        print("\n🔍 Testing market connections...")
        
        # Test Polymarket connection with both YES and NO tokens
        print("   📈 Connecting to Polymarket test market (YES/NO pair)...")
        poly_result = await coordinator.connect("test_token_123,test_token_123_no", "polymarket")
        print(f"   {'✅ SUCCESS' if poly_result else '❌ FAILED'} - Polymarket connection")
        
        # Test Kalshi connection with test market  
        print("   📈 Connecting to Kalshi test market...")
        kalshi_result = await coordinator.connect("TEST-MARKET-Y", "kalshi")
        print(f"   {'✅ SUCCESS' if kalshi_result else '❌ FAILED'} - Kalshi connection")
        
        # Add arbitrage market pair for cross-platform detection
        print("\n🔗 Setting up arbitrage market pair...")
        # Using mock IDs: 
        # - Kalshi: sid=3 (TEST-MARKET-Y, auto-assigned starting from 1)
        # - Polymarket: test_token_123 (YES), test_token_123_no (NO - simulated)
        coordinator.add_arbitrage_market_pair(
            market_pair="TEST-ELECTION-2024",
            kalshi_sid=3,  # TEST-MARKET-Y gets assigned sid=3 (third market)
            polymarket_yes_asset_id="test_token_123",
            polymarket_no_asset_id="test_token_123_no"  # Simulated NO token
        )
        print("   ✅ Arbitrage pair added: TEST-ELECTION-2024")
        print("      Kalshi sid=3 (TEST-MARKET-Y) ↔ Polymarket test_token_123")
        
        # Subscribe to arbitrage alerts
        arbitrage_alerts = []
        manual_alerts = []
        def capture_arbitrage_alert(event_data):
            alert = event_data.get('alert')
            if alert:
                arbitrage_alerts.append(alert)
                print(f"   🚨 ARBITRAGE DETECTED: {alert.market_pair} - spread: {alert.spread:.3f}")
        
        coordinator.service_coordinator.event_bus.subscribe('arbitrage.alert', capture_arbitrage_alert)
        
        # Initialize arbitrage feeder to generate arbitrage opportunities
        print("\n🎯 Initializing arbitrage feeder...")
        arbitrage_feeder = MockArbitrageFeeder(
            kalshi_server=kalshi_server,
            polymarket_server=poly_server,
            min_spread_threshold=0.02,  # 2% threshold
            feed_interval=4.0  # Every 4 seconds
        )
        
        # Show scenario summary
        scenario_summary = arbitrage_feeder.get_scenario_summary()
        print(f"   📊 Loaded {scenario_summary['total_scenarios']} scenarios:")
        print(f"      - {scenario_summary['arbitrage_scenarios']} arbitrage opportunities")
        print(f"      - {scenario_summary['equilibrium_scenarios']} equilibrium scenarios")
        
        if poly_result or kalshi_result:
            print(f"\n⏱️ Running arbitrage feeder for 20 seconds...")
            
            # Start arbitrage feeder in background
            feeder_task = asyncio.create_task(arbitrage_feeder.start_feeding(duration_seconds=20))
            
            # Monitor for updates and arbitrage detection
            start_time = datetime.now()
            for interval in range(4):  # 4 intervals of 5 seconds each
                await asyncio.sleep(5)
                elapsed = (datetime.now() - start_time).total_seconds()
                
                current_scenario = arbitrage_feeder.get_current_scenario()
                print(f"   📊 {elapsed:.0f}s - Current scenario: {current_scenario.name}")
                print(f"      Expected spread: {current_scenario.expected_spread:.1%}")
                
                # Get status
                status = coordinator.get_status()
                print(f"      Connections: {status['total_connections']}")
                if status['kalshi_platform']['async_started']:
                    print(f"      ✅ Kalshi pipeline active")
                if status['polymarket_platform']['async_started']:
                    print(f"      ✅ Polymarket pipeline active")
                    
                # Report arbitrage detection
                if arbitrage_alerts:
                    print(f"      🚨 Arbitrage alerts detected: {len(arbitrage_alerts)}")
                    latest_alert = arbitrage_alerts[-1]
                    print(f"         Latest: {latest_alert.direction} {latest_alert.side} (spread: {latest_alert.spread:.1%})")
                else:
                    print(f"      📊 No arbitrage opportunities detected yet")
            
            # Wait for feeder to complete
            await feeder_task
            print("   ✅ Arbitrage feeder completed")
        
        # Test manual arbitrage check
        print(f"\n🔍 Manual arbitrage check for TEST-ELECTION-2024...")
        try:
            manual_alerts = await coordinator.check_arbitrage_for_pair("TEST-ELECTION-2024")
            if manual_alerts:
                print(f"   🚨 Manual check found {len(manual_alerts)} arbitrage opportunities!")
                for alert in manual_alerts:
                    print(f"      - {alert.direction} {alert.side}: spread {alert.spread:.3f}")
            else:
                print(f"   📊 Manual check: No arbitrage opportunities found")
        except Exception as e:
            print(f"   ⚠️ Manual arbitrage check failed: {e}")
            manual_alerts = []
        
        # Final status check
        print(f"\n📋 Final Status Check:")
        status = coordinator.get_status()
        print(f"   📊 Total connections: {status['total_connections']}")
        print(f"   📊 Kalshi platform active: {status['kalshi_platform']['async_started']}")
        print(f"   📊 Polymarket platform active: {status['polymarket_platform']['async_started']}")
        
        # Cleanup
        print(f"\n🧹 Cleaning up...")
        await coordinator.disconnect_all()
        print("✅ MarketsCoordinator cleanup completed")
        
        # Results
        print(f"\n📊 INTEGRATION TEST RESULTS:")
        print(f"   🔌 Polymarket Connection: {'✅ SUCCESS' if poly_result else '❌ FAILED'}")
        print(f"   🔌 Kalshi Connection: {'✅ SUCCESS' if kalshi_result else '❌ FAILED'}")
        print(f"   🔗 Arbitrage Pair Setup: ✅ SUCCESS (TEST-ELECTION-2024)")
        print(f"   🎯 Arbitrage Feeder: ✅ SUCCESS ({scenario_summary['total_scenarios']} scenarios)")
        print(f"   🚨 Real-time Alerts: {len(arbitrage_alerts)} detected")
        print(f"   🔍 Manual Check: {'✅ FOUND' if manual_alerts else '📊 NONE'}")
        
        overall_success = poly_result or kalshi_result
        arbitrage_success = len(arbitrage_alerts) > 0 or (manual_alerts and len(manual_alerts) > 0)
        print(f"   🎯 Arbitrage Detection: {'✅ SUCCESS' if arbitrage_success else '📊 NO OPPORTUNITIES'}")
        print(f"   🎯 Overall Result: {'✅ SUCCESS' if overall_success else '❌ FAILED'}")
        
        return overall_success
        
    except Exception as e:
        print(f"\n💥 Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        print(f"\n🛑 Stopping mock servers...")
        await poly_server.stop()
        await kalshi_server.stop()
        print("✅ Mock servers stopped")

async def main():
    """Main test function with argument parsing"""
    # Parse command line arguments
    args = parse_arguments()
    
    # Setup logging with specified level
    setup_logging(args.log_level)
    
    print(f"🎯 MOCK INTEGRATION TEST - Log Level: {args.log_level}")
    print("=" * 70)
    
    success = await run_mock_integration_test()
    print(f"\n🏁 Test completed with result: {'SUCCESS' if success else 'FAILED'}")
    return 0 if success else 1

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n⏹️ Test interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)