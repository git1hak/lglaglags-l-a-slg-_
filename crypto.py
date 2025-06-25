import os
import logging
import aiohttp
from typing import Dict, Optional, Tuple, Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# CryptoBot API settings
CRYPTO_BOT_TOKEN = os.getenv('CRYPTO_BOT_TOKEN', '419864:AAZiQpBh3udq87RGowXov9jObx2v3NLeJUC')
API_URL = 'https://pay.crypt.bot/api/'

class CryptoPay:
    def __init__(self, token: str = None):
        """Initialize CryptoPay with optional token override"""
        self.token = token or CRYPTO_BOT_TOKEN
        self.session = None
        if not self.token:
            raise ValueError("CryptoBot token is required")

    async def _make_request(self, method: str, endpoint: str, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Make API request to CryptoBot
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint
            **kwargs: Additional arguments for the request
            
        Returns:
            Dictionary with API response or None if request failed
        """
        url = f"{API_URL}{endpoint}"
        headers = {
            'Crypto-Pay-API-Token': self.token,
            'Content-Type': 'application/json'
        }
        
        # Update headers if provided in kwargs
        if 'headers' in kwargs:
            headers.update(kwargs.pop('headers'))
        
        try:
            if self.session is None:
                self.session = aiohttp.ClientSession()
            
            async with self.session.request(
                method=method,
                url=url,
                headers=headers,
                **kwargs
            ) as response:
                data = await response.json()
                
                # Log error if request was not successful
                if not data.get('ok', False):
                    error_msg = data.get('error', {}).get('name', 'Unknown error')
                    logger.error(f"API error in {endpoint}: {error_msg}")
                    return None
                    
                return data.get('result')
                
        except aiohttp.ClientError as e:
            logger.error(f"Network error in {endpoint}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in {endpoint}: {str(e)}")
            return None

    async def create_invoice(
        self,
        user_id: int,
        amount: float,
        description: str,
        payload: str = None,
        asset: str = 'USDT',
        allow_anonymous: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Create a new payment invoice
        
        Args:
            user_id: Telegram user ID
            amount: Invoice amount
            description: Invoice description
            payload: Additional data to store with the invoice
            asset: Cryptocurrency to use (default: USDT)
            allow_anonymous: Allow anonymous payments
            
        Returns:
            Dictionary with invoice data or None if failed
        """
        data = {
            'asset': asset,
            'amount': str(amount),
            'description': description,
            'payload': payload or str(user_id),
            'allow_anonymous': allow_anonymous,
            'paid_btn_url': 'https://t.me/Keeper020bot',  # Replace with your bot URL
            'paid_btn_name': 'viewItem'  # Valid values: 'viewItem', 'openChannel', 'openBot', 'callbackURL'
        }
        
        result = await self._make_request(
            'POST',
            'createInvoice',
            json=data
        )
        
        if result:
            logger.info(f"Created invoice for user {user_id}: {result.get('invoice_id')}")
        else:
            logger.error(f"Failed to create invoice for user {user_id}")
            
        return result

    async def get_invoice(self, invoice_id: int) -> Optional[Dict[str, Any]]:
        """
        Get invoice details by ID
        
        Args:
            invoice_id: ID of the invoice to retrieve
            
        Returns:
            Dictionary with invoice data or None if not found
        """
        if not invoice_id:
            logger.error("No invoice ID provided")
            return None
            
        result = await self._make_request(
            'GET',
            'getInvoices',
            params={'invoice_ids': str(invoice_id)}
        )
        
        if result and 'items' in result and result['items']:
            return result
        return None

    async def get_exchange_rates(self) -> Optional[Dict[str, Any]]:
        """Get current exchange rates"""
        return await self._make_request('GET', 'getExchangeRates')

    async def get_balance(self) -> Optional[Dict[str, Any]]:
        """Get bot balance"""
        return await self._make_request('GET', 'getBalance')

    async def close(self) -> None:
        """Close the HTTP session"""
        if self.session:
            await self.session.close()
            self.session = None
            logger.info("CryptoPay session closed")

# Global instance
crypto_pay = CryptoPay()

# Helper function to get tariff info (can be moved to another module if needed)
def get_tariff_info(tariff_id: str) -> Tuple[float, str, int]:
    """
    Get tariff price, description, and days
    
    Args:
        tariff_id: ID of the tariff
        
    Returns:
        Tuple of (price, description, days)
    """
    tariffs = {
        '1day': (2.0, "1 день", 1),
        '3days': (3.0, "3 дня", 3),
        '7days': (5.0, "7 дней", 7),
        '30days': (9.0, "30 дней", 30),
        'forever': (13.0, "Навсегда", 3650)  # ~10 years
    }
    return tariffs.get(tariff_id, (0.0, "Неизвестный тариф", 0))

async def init_crypto_pay():
    """Initialize CryptoPay and verify the token"""
    try:
        balance = await crypto_pay.get_balance()
        if balance:
            logger.info("CryptoPay initialized successfully")
            return True
        logger.error("Failed to initialize CryptoPay: Invalid token or network error")
        return False
    except Exception as e:
        logger.error(f"Error initializing CryptoPay: {str(e)}")
        return False