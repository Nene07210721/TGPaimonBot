import typing

import aiohttp.typedefs
import genshin  # pylint: disable=W0406
import yarl
from genshin import constants, types, utility, models
from genshin.client import routes
from genshin.utility import generate_dynamic_secret

from modules.apihelper.helpers import get_device_id, get_ds, get_ua, hex_digest
from utils.patch.methods import patch, patchable

DEVICE_ID = get_device_id()


def get_account_mid_v2(cookies: typing.Dict[str, str]) -> typing.Optional[str]:
    for name, value in cookies.items():
        if name == "account_mid_v2":
            return value

    return None


@patch(genshin.client.components.calculator.CalculatorClient)  # noqa
class CalculatorClient:
    @patchable
    async def get_character_details(
        self,
        character: genshin.types.IDOr[genshin.models.genshin.Character],
        *,
        uid: typing.Optional[int] = None,
        lang: typing.Optional[str] = None,
    ):
        uid = uid or await self._get_uid(genshin.types.Game.GENSHIN)

        data = await self.request_calculator(
            "sync/avatar/detail",
            method="GET",
            lang=lang,
            params=dict(
                avatar_id=int(character),
                uid=uid,
                region=genshin.utility.recognize_genshin_server(uid),
            ),
        )
        if data.get("weapon") is None:
            weapon = {
                "id": character.weapon.id,
                "name": character.weapon.name,
                "icon": character.weapon.icon,
                "weapon_cat_id": character.weapon.type,
                "weapon_level": character.weapon.rarity,
                "max_level": 90,
                "level_current": character.weapon.level,
            }
            data["weapon"] = weapon
        return genshin.models.genshin.CalculatorCharacterDetails(**data)


@patch(genshin.client.components.base.BaseClient)  # noqa
class BaseClient:
    @patchable
    async def request_hoyolab(
        self,
        url: aiohttp.typedefs.StrOrURL,
        *,
        lang: typing.Optional[str] = None,
        region: typing.Optional[types.Region] = None,
        method: typing.Optional[str] = None,
        params: typing.Optional[typing.Mapping[str, typing.Any]] = None,
        data: typing.Any = None,
        headers: typing.Optional[aiohttp.typedefs.LooseHeaders] = None,
        **kwargs: typing.Any,
    ) -> typing.Mapping[str, typing.Any]:
        """Make a request any hoyolab endpoint."""
        if lang is not None and lang not in constants.LANGS:
            raise ValueError(f"{lang} is not a valid language, must be one of: " + ", ".join(constants.LANGS))

        lang = lang or self.lang
        region = region or self.region

        url = routes.TAKUMI_URL.get_url(region).join(yarl.URL(url))

        if region == types.Region.OVERSEAS:
            headers = {
                "x-rpc-app_version": "1.5.0",
                "x-rpc-client_type": "4",
                "x-rpc-language": lang,
                "ds": generate_dynamic_secret(),
            }
        elif region == types.Region.CHINESE:
            account_id = self.cookie_manager.user_id
            if account_id:
                device_id = hex_digest(str(account_id))
            else:
                account_mid_v2 = get_account_mid_v2(self.cookie_manager.cookies)
                if account_mid_v2:
                    device_id = hex_digest(account_mid_v2)
                else:
                    device_id = DEVICE_ID
            app_version, client_type, ds_sign = get_ds(new_ds=True, data=data, params=params)
            ua = get_ua(device="Paimon Build " + device_id[0:5], version=app_version)
            headers = {
                "User-Agent": ua,
                "X_Requested_With": "com.mihoyo.hoyolab",
                "Referer": "https://webstatic-sea.hoyolab.com",
                "x-rpc-device_id": get_device_id(device_id),
                "x-rpc-app_version": app_version,
                "x-rpc-client_type": client_type,
                "ds": ds_sign,
            }
        else:
            raise TypeError(f"{region!r} is not a valid region.")

        data = await self.request(url, method=method, params=params, data=data, headers=headers, **kwargs)
        return data

    @patchable
    async def request(
        self,
        url: aiohttp.typedefs.StrOrURL,
        *,
        method: typing.Optional[str] = None,
        params: typing.Optional[typing.Mapping[str, typing.Any]] = None,
        data: typing.Any = None,
        headers: typing.Optional[aiohttp.typedefs.LooseHeaders] = None,
        cache: typing.Any = None,
        static_cache: typing.Any = None,
        **kwargs: typing.Any,
    ) -> typing.Mapping[str, typing.Any]:
        """Make a request and return a parsed json response."""
        if cache is not None:
            value = await self.cache.get(cache)
            if value is not None:
                return value
        elif static_cache is not None:
            value = await self.cache.get_static(static_cache)
            if value is not None:
                return value

        # actual request

        headers = dict(headers or {})
        headers.setdefault("User-Agent", self.USER_AGENT)

        if method is None:
            method = "POST" if data else "GET"

        if "json" in kwargs:
            raise TypeError("Use data instead of json in request.")

        await self._request_hook(method, url, params=params, data=data, headers=headers, **kwargs)

        response = await self.cookie_manager.request(
            url,
            method=method,
            params=params,
            json=data,
            headers=headers,
            **kwargs,
        )

        # cache

        if cache is not None:
            await self.cache.set(cache, response)
        elif static_cache is not None:
            await self.cache.set_static(static_cache, response)

        return response


@patch(genshin.client.components.daily.DailyRewardClient)  # noqa
class DailyRewardClient:
    @patchable
    async def request_daily_reward(
        self,
        endpoint: str,
        *,
        game: typing.Optional[types.Game] = None,
        method: str = "GET",
        lang: typing.Optional[str] = None,
        params: typing.Optional[typing.Mapping[str, typing.Any]] = None,
        headers: typing.Optional[aiohttp.typedefs.LooseHeaders] = None,
        **kwargs: typing.Any,
    ) -> typing.Mapping[str, typing.Any]:
        """Make a request towards the daily reward endpoint."""
        params = dict(params or {})
        headers = dict(headers or {})

        if game is None:
            if self.default_game is None:
                raise RuntimeError("No default game set.")

            game = self.default_game

        base_url = routes.REWARD_URL.get_url(self.region, game)
        url = (base_url / endpoint).update_query(**base_url.query)

        if self.region == types.Region.OVERSEAS:
            params["lang"] = lang or self.lang

        elif self.region == types.Region.CHINESE:
            # TODO: Support cn honkai
            player_id = await self._get_uid(types.Game.GENSHIN)

            params["uid"] = player_id
            params["region"] = utility.recognize_genshin_server(player_id)

            account_id = self.cookie_manager.user_id
            if account_id:
                device_id = hex_digest(str(account_id))
            else:
                account_mid_v2 = get_account_mid_v2(self.cookie_manager.cookies)
                if account_mid_v2:
                    device_id = hex_digest(account_mid_v2)
                else:
                    device_id = DEVICE_ID
            if endpoint == "sign":
                app_version, client_type, ds_sign = get_ds()
            else:
                app_version, client_type, ds_sign = get_ds(new_ds=True, params=params)
            device = "Paimon Build " + device_id[0:5]
            ua = get_ua(device=device)
            headers["User-Agent"] = ua
            headers["X_Requested_With"] = "com.mihoyo.hoyolab"
            headers["Referer"] = (
                "https://webstatic.mihoyo.com/bbs/event/signin-ys/index.html?"
                "bbs_auth_required=true&act_id=e202009291139501&utm_source=bbs&utm_medium=mys&utm_campaign=icon"
            )
            headers["x-rpc-device_name"] = device
            headers["x-rpc-device_id"] = get_device_id(device_id)
            headers["x-rpc-app_version"] = app_version
            headers["x-rpc-client_type"] = client_type
            headers["x-rpc-sys_version"] = "12"
            headers["x-rpc-platform"] = "android"
            headers["x-rpc-channel"] = "miyousheluodi"
            headers["x-rpc-device_model"] = device
            headers["ds"] = ds_sign

            validate = kwargs.get("validate")
            challenge = kwargs.get("challenge")

            if validate and challenge:
                headers["x-rpc-challenge"] = challenge
                headers["x-rpc-validate"] = validate
                headers["x-rpc-seccode"] = f"{validate}|jordan"

        else:
            raise TypeError(f"{self.region!r} is not a valid region.")

        kwargs.pop("challenge", None)
        kwargs.pop("validate", None)

        return await self.request(url, method=method, params=params, headers=headers, **kwargs)


@patch(genshin.client.components.hoyolab.HoyolabClient)  # noqa
class HoyolabClient:
    @patchable
    async def get_hoyolab_user(
        self, hoyolab_id: int, *, lang: typing.Optional[str] = None
    ) -> models.PartialHoyolabUser:
        """Get a hoyolab user."""
        # todo: use routes.py instead of putting full urls in methods
        if self.region == types.Region.OVERSEAS:
            if hoyolab_id <= 0:
                raise TypeError(f"{hoyolab_id} is not a valid hoyolab id.")
            url = "https://bbs-api-os.hoyolab.com/community/painter/wapi/user/full"
            data = await self.request_hoyolab(url, params=dict(uid=hoyolab_id), lang=lang)
            return models.FullHoyolabUser(**data["user_info"])
        elif self.region == types.Region.CHINESE:
            url = "https://bbs-api.mihoyo.com/user/wapi/getUserFullInfo"
            account_id = self.cookie_manager.user_id
            if account_id:
                device_id = hex_digest(str(account_id))
            else:
                account_mid_v2 = get_account_mid_v2(self.cookie_manager.cookies)
                if account_mid_v2:
                    device_id = hex_digest(account_mid_v2)
                else:
                    device_id = DEVICE_ID
            ds_sign = generate_dynamic_secret("ulInCDohgEs557j0VsPDYnQaaz6KJcv5")
            ua = get_ua(device="Paimon Build " + device_id[0:5], version="2.40.0")
            headers = {
                "User-Agent": ua,
                "Referer": "https://bbs.mihoyo.com/",
                "x-rpc-device_id": get_device_id(device_id),
                "x-rpc-app_version": "2.40.0",
                "x-rpc-client_type": "4",
                "ds": ds_sign,
            }
            data = await self.request(url, method="GET", params=dict(gids=2), headers=headers)
            return models.PartialHoyolabUser(**data["user_info"])
        else:
            raise TypeError(f"{self.region!r} is not a valid region.")
