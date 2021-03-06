import os
import threading
import json
from time import sleep

from logzero import logger
from twisted.internet import reactor, task, endpoints
from twisted.web.server import Request, Site
from klein import Klein, resource

from neo.Network.NodeLeader import NodeLeader
from neo.Core.Blockchain import Blockchain
from neo.Implementations.Blockchains.LevelDB.LevelDBBlockchain import LevelDBBlockchain
from neo.Settings import settings

from neo.Network.api.decorators import json_response, gen_authenticated_decorator, catch_exceptions
from neo.contrib.smartcontract import SmartContract
from neo.SmartContract.ContractParameter import ContractParameter, ContractParameterType

# Set the hash of your contract here:
SMART_CONTRACT_HASH = "0xffb1c97830cf6de4cec115c623dc9e1c321df451"

# Default REST API port is 8080, and can be overwritten with an env var:
API_PORT = os.getenv("NEO_REST_API_PORT", 8080)

# If you want to enable logging to a file, set the filename here:
LOGFILE = os.getenv("NEO_REST_LOGFILE", None)

# Internal: if LOGFILE is set, file logging will be setup with max
# 10 MB per file and 3 rotations:
if LOGFILE:
    settings.set_logfile(LOGFILE, max_bytes=1e7, backup_count=3)

# Internal: get the API token from an environment variable
API_AUTH_TOKEN = os.getenv("NEO_REST_API_TOKEN", None)
if not API_AUTH_TOKEN:
    raise Exception("No NEO_REST_API_TOKEN environment variable found!")

# Internal: setup the smart contract instance
smart_contract = SmartContract(SMART_CONTRACT_HASH)

# Internal: setup the klein instance
app = Klein()

# Internal: generate the @authenticated decorator with valid tokens
authenticated = gen_authenticated_decorator(API_AUTH_TOKEN)

#
# Smart contract event handler for Runtime.Notify events
#


@smart_contract.on_notify
def sc_notify(event):
    # logger.info("SmartContract Runtime.Notify event: %s", event)
    logger.info("payload %s", event.event_payload.Value)

def custom_background_code():
    """ Custom code run in a background thread. Prints the current block height.
    This function is run in a daemonized thread, which means it can be instantly killed at any
    moment, whenever the main thread quits. If you need more safety, don't use a  daemonized
    thread and handle exiting this thread in another way (eg. with signals and events).
    """
    while True:
        logger.info("Block %s / %s", str(Blockchain.Default().Height), str(Blockchain.Default().HeaderHeight))
        sleep(15)


#
# REST API Routes
#
@app.route('/')
def home(request):
    return "Hello world"


@app.route('/echo/<msg>')
@catch_exceptions
@authenticated
@json_response
def echo_msg(request, msg):
    return {
        "echo": msg
    }


@app.route('/echo-post', methods=['POST'])
@catch_exceptions
@authenticated
@json_response
def echo_post(request):
    # Parse POST JSON body
    body = json.loads(request.content.read().decode("utf-8"))

    # Echo it
    return {
        "post-body": body
    }

#
# Main method which starts everything up
#


def main():
    # Use TestNet
    settings.setup_privnet(host='localhost')

    # Setup the blockchain
    blockchain = LevelDBBlockchain(settings.chain_leveldb_path)
    Blockchain.RegisterBlockchain(blockchain)
    dbloop = task.LoopingCall(Blockchain.Default().PersistBlocks)
    dbloop.start(.1)
    NodeLeader.Instance().Start()

    # Disable smart contract events for external smart contracts
    settings.set_log_smart_contract_events(False)

    # Start a thread with custom code
    d = threading.Thread(target=custom_background_code)
    d.setDaemon(True)  # daemonizing the thread will kill it when the main thread is quit
    d.start()

    # Hook up Klein API to Twisted reactor.
    endpoint_description = "tcp:port=%s:interface=localhost" % API_PORT

    # If you want to make this service externally available (not only at localhost),
    # then remove the `interface=localhost` part:
    # endpoint_description = "tcp:port=%s" % API_PORT

    endpoint = endpoints.serverFromString(reactor, endpoint_description)
    endpoint.listen(Site(app.resource()))

    # Run all the things (blocking call)
    logger.info("Everything setup and running. Waiting for events...")
    reactor.run()
    logger.info("Shutting down.")


if __name__ == "__main__":
    main()