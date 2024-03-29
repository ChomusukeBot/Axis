import aiohttp
import asyncio
import os
import sanic
import sys
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from tools import parse_url
from urllib.parse import parse_qs

# Create the asyncio event loop
LOOP = asyncio.get_event_loop()

# The authentication redirection URLs
AUTH_GITHUB = "https://github.com/login/oauth/authorize?client_id={0}&redirect_uri={1}"  # noqa: E501
CODE_GITHUB = "https://github.com/login/oauth/access_token?client_id={0}&client_secret={1}&code={2}"  # noqa: E501
USER_GITHUB = "https://api.github.com/user"

# Load the .env and unload the lib
load_dotenv()
del load_dotenv

# Create the basic Sanic application
APP = sanic.Sanic()
# If there is no MongoDB URL, exit with code 2
if "MONGO_URL" not in os.environ:
    sys.exit(2)

# Create the instance and make sure that is valid
MONGO = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=LOOP)
MONGO.admin.command("ismaster")
DATABASE = MONGO["chomusuke"]
COLLECTION = DATABASE["users"]


@APP.route("/")
async def home(request):
    """
    Basic endpoint that redirects to the GitHub organization.
    """
    return sanic.response.redirect("https://github.com/ChomusukeBot",
                                   status=302)


@APP.route("/github")
async def github(request):
    """
    Endpoint that handles the GitHub login basics.
    """
    # If there is no GitHub Client or Secret, return a 503 Service Unavailable
    if "GITHUB_CLIENT" not in os.environ or "GITHUB_SECRET" not in os.environ:
        return sanic.response.text("GitHub is not supported at this time.",
                                   status=503)

    # If there is no Discord ID on the query string
    if "id" not in request.args:
        return sanic.response.text("The Discord ID was not specified",
                                   status=400)

    # Format the URL that we are going to redirect to
    callback = "{0}/github/callback".format(parse_url(request.url))
    redirect = AUTH_GITHUB.format(os.environ["GITHUB_CLIENT"], callback)
    # Create a 301 with the correct URL
    response = sanic.response.redirect(redirect, status=301)
    response.cookies["id"] = request.args["id"][0]
    # And return it
    return response


@APP.route("/github/callback")
async def github_callback(request):
    """
    Endpoint that handles the GitHub login basics.
    """
    # If there is no GitHub Client or Secret, return a 503 Service Unavailable
    if "GITHUB_CLIENT" not in os.environ or "GITHUB_SECRET" not in os.environ:
        return sanic.response.text("GitHub is not supported at this time.",
                                   status=503)

    # If there is no Discord ID
    if "id" not in request.cookies:
        return sanic.response.text("No Discord ID present on cookies.",
                                   status=400)

    # If there is a Discord ID but is not numeric
    if not request.cookies["id"].isnumeric():
        return sanic.response.text("The Discord ID is not numeric.",
                                   status=400)

    # If there is no code returned by GitHub
    if "code" not in request.args:
        return sanic.response.text("There is no GitHub code.",
                                   status=400)

    # Format the URL that we are going to request
    url = CODE_GITHUB.format(os.environ["GITHUB_CLIENT"],
                             os.environ["GITHUB_SECRET"],
                             request.args["code"][0])
    # Make a web request for getting the user token
    async with aiohttp.ClientSession() as client:
        async with client.get(url) as resp:
            # Because GitHub answers with a code 200 always
            # Parse the parameters on the body
            params = parse_qs(await resp.text())

    # If there is an error on the parameters
    if "error" in params:
        # Return a 400 response with the message from GitHub
        return sanic.response.text(params["error_description"][0], status=400)

    # Format the headers for the next request
    headers = {
        "Authorization": "token {0}".format(params["access_token"][0]),
        "User-Agent": "Chomusuke (+https://github.com/ChomusukeBot)"
    }
    # If there are no errors, make another request for the real token
    async with aiohttp.ClientSession() as client:
        async with client.get(USER_GITHUB, headers=headers) as resp:
            # If the code is not 200
            if resp.status != 200:
                return sanic.response.text("An error has ocurred while fetching your data.",  # noqa: E501
                                           status=resp.status)
            # Save the response as JSON
            json = await resp.json()

    # Save the ID as a number
    _id = int(request.cookies["id"])

    # Try to look for an item
    found = await COLLECTION.find_one({"_id": _id})
    # If there is an item, update it
    if found:
        await COLLECTION.update_one({"_id": _id},
                                    {"$set": {"github": json["login"]}})
    # Otherwise, insert a new one
    else:
        await COLLECTION.insert_one({"_id": _id,
                                    "github": json["login"]})

    # Tell the user that we are done
    return sanic.response.text("Done! The GitHub account {0} is now linked with Discord.".format(json["login"]),  # noqa: E501
                               status=200)


if __name__ == "__main__":
    server = APP.create_server(host="0.0.0.0", port=42013,
                               return_asyncio_server=True)
    task = asyncio.ensure_future(server, loop=LOOP)
    LOOP.run_forever()
