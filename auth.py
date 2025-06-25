import os
import asyncio
from telethon import TelegramClient
from telethon.tl.functions.messages import ReportRequest
from telethon.tl.types import (
    InputReportReasonSpam,
    InputPeerChannel, InputPeerChat, InputPeerUser
)
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Get API credentials from environment variables
API_ID = int(os.getenv('TELEGRAM_API_ID', '20045757'))
API_HASH = os.getenv('TELEGRAM_API_HASH', '7d3ea0c0d4725498789bd51a9ee02421')

# Session directory
SESSIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sessions')
os.makedirs(SESSIONS_DIR, exist_ok=True)

# Report reason - using spam by default
DEFAULT_REASON = InputReportReasonSpam()

class AuthManager:
    def __init__(self):
        self.clients = []
        self.initialized = False

    async def init_clients(self):
        """Initialize all Telethon clients from session files"""
        if not os.path.exists(SESSIONS_DIR):
            logger.warning(f"Sessions directory {SESSIONS_DIR} not found")
            return []

        session_files = [f for f in os.listdir(SESSIONS_DIR) 
                        if f.endswith('.session')]
        
        if not session_files:
            logger.warning(f"No session files found in {SESSIONS_DIR}")
            return []

        for session_file in session_files:
            try:
                session_path = os.path.join(SESSIONS_DIR, session_file)
                client = TelegramClient(
                    session_path,
                    API_ID,
                    API_HASH,
                    device_model="ASUS ROG Zephyrus GA401QM",
                    system_version="Windows 11",
                    app_version="5.11.1 x64",
                    lang_code="en",
                    system_lang_code="en"
                )
                
                await client.start()
                if await client.is_user_authorized():
                    self.clients.append(client)
                    logger.info(f"Successfully initialized session: {session_file}")
                else:
                    logger.warning(f"Session not authorized: {session_file}")
                    await client.disconnect()
            except Exception as e:
                logger.error(f"Error initializing session {session_file}: {e}")
        
        self.initialized = True
        return len(self.clients)

    async def close(self):
        """Close all client connections"""
        for client in self.clients:
            try:
                await client.disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting client: {e}")
        self.clients = []
        self.initialized = False

    @staticmethod
    def parse_message_link(link: str) -> tuple:
        """Parse Telegram message link to get chat and message ID"""
        try:
            # Handle t.me/c/ links (channels and supergroups)
            if '/c/' in link:
                parts = link.split('/')
                chat_id = int('-100' + parts[4])
                message_id = int(parts[5])
                return chat_id, message_id
            # Handle t.me/username/123 links (public groups and users)
            else:
                parts = link.split('/')
                username = parts[3]
                message_id = int(parts[4])
                return username, message_id
        except (IndexError, ValueError) as e:
            logger.error(f"Error parsing message link {link}: {e}")
            return None, None

    async def send_report(self, client, peer, msg_id):
        """Send a single report using a client"""
        try:
            from telethon.tl.types import InputPeerChannel, InputPeerChat, InputPeerUser
            
            # Get the full entity
            entity = await client.get_entity(peer)
            
            # Create the appropriate InputPeer
            if hasattr(entity, 'channel_id'):
                input_peer = InputPeerChannel(
                    channel_id=entity.id,
                    access_hash=entity.access_hash
                )
            elif hasattr(entity, 'chat_id'):
                input_peer = InputPeerChat(chat_id=entity.id)
            else:
                input_peer = InputPeerUser(
                    user_id=entity.id,
                    access_hash=entity.access_hash
                )
            
            # Send the report
            result = await client(ReportRequest(
                peer=input_peer,
                id=[msg_id],
                reason=InputReportReasonSpam(),
                message=''  # Empty message as required by the API
            ))
            return True, None
        except Exception as e:
            logger.error(f"Error sending report: {e}")
            return False, str(e)

    async def send_reports(self, link: str) -> dict:
        """Send reports from all active sessions"""
        if not self.initialized:
            await self.init_clients()
        
        if not self.clients:
            return {"success": 0, "total": 0, "errors": ["No active sessions available"]}
        
        peer, msg_id = self.parse_message_link(link)
        if not peer or not msg_id:
            return {"success": 0, "total": 0, "errors": ["Invalid message link"]}
        
        results = {
            "success": 0,
            "total": len(self.clients),
            "errors": []
        }
        
        tasks = []
        for client in self.clients:
            task = asyncio.create_task(
                self.send_report(client, peer, msg_id)
            )
            tasks.append(task)
        
        # Wait for all reports to complete
        report_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in report_results:
            if isinstance(result, Exception):
                results["errors"].append(str(result))
            elif result[0]:  # success
                results["success"] += 1
            else:  # error
                results["errors"].append(result[1])
        
        return results

# Global instance
auth_manager = AuthManager()

async def init_auth():
    """Initialize auth manager"""
    count = await auth_manager.init_clients()
    logger.info(f"Initialized {count} Telegram sessions")
    return count

async def close_auth():
    """Close all auth connections"""
    await auth_manager.close()
    logger.info("Closed all Telegram sessions")