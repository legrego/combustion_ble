"""Food Safe Data.

NOTE: This file does not have an upstream match
"""

from enum import Enum, unique


@unique
class FoodSafeMode(Enum):
    """Food Safe Mode."""

    SIMPLIFIED = 0x00
    INTEGRATED = 0x01


class Product(Enum):
    pass


@unique
class SimplifiedProduct(Product):
    """Selected product for food-safety using the simplified mode."""

    DEFAULT = 0x00
    ANY_POULTRY = 0x01
    BEEF_CUTS = 0x02
    PORK_CUTS = 0x03
    VEAL_CUTS = 0x04
    LAMB_CUTS = 0x05
    GROUND_MEATS = 0x06
    HAM_FRESH_SMOKED = 0x07
    HAM_COOKED = 0x08
    EGGS = 0x09
    FISH = 0xA
    LEFTOVERS = 0xB
    CASSEROLES = 0xC


@unique
class IntegratedProduct(Product):
    """Selected product for food-safety using the integrated mode."""

    DEFAULT = 0x00
    BEEF = 0x01
    BEEF_GROUND = 0x02
    CHICKEN = 0x03
    CHICKEN_GROUND = 0x04
    PORK = 0x05
    PORK_GROUND = 0x06
    HAM = 0x07
    HAM_GROUND = 0x08
    TURKEY = 0x09
    TURKEY_GROUND = 0xA
    LAMB = 0xB
    LAMB_GROUND = 0xC
    FISH = 0xD
    FISH_GROUND = 0xE
    DAIRY = 0xF
    CUSTOM = 0x3FF


@unique
class Serving(Enum):
    """Serving options for which safety calculations are available."""

    SERVED_IMMEDIATELY = 0
    COOKED_AND_CHILLED = 1


class FoodSafeData:
    def __init__(
        self,
        food_safe_mode: FoodSafeMode,
        product: Product,
        serving: Serving,
        selected_threshold_reference_temperature: float,
        z_value: float,
        reference_temperature: float,
        d_value_at_rt: float,
        target_log_reduction: float,
    ) -> None:
        self.food_safe_mode = food_safe_mode
        self.product = product
        self.serving = serving
        self.selected_threshold_reference_temperature = selected_threshold_reference_temperature
        self.z_value = z_value
        self.reference_temperature = reference_temperature
        d_value_at_rt = d_value_at_rt
        target_log_reduction = target_log_reduction

    @classmethod
    def from_raw(cls, data: bytes):
        # ____LLLL LLLLDDDD DDDDDDDD DRRRRRRR RRRRRRZZ ZZZZZZZZ ZZZTTTTT TTTTTTTT SSSPPPPP PPPPPMMM
        # 00000100 01101000 11111001 00010010 11000000 00001101 10000100 11101000 00100000 00100001

        payload = list(data)
        payload.reverse()

        mode_raw = payload[9] & 0x7
        mode = FoodSafeMode(mode_raw)

        product_raw = ((payload[8] & 0x1F) << 5) | (payload[9] >> 3)
        product: Product | None = None
        if mode == FoodSafeMode.SIMPLIFIED:
            product = SimplifiedProduct(product_raw)
        elif mode == FoodSafeMode.INTEGRATED:
            product = IntegratedProduct(product_raw)

        serving_raw = payload[8] >> 5
        serving = Serving(serving_raw)

        threshold_ref_temp_raw = ((payload[6] & 0x1F) << 8) | payload[7]
        threshold_ref_temp = float(threshold_ref_temp_raw) * 0.05

        z_value_raw = ((payload[4] & 0x03) << 11) | (payload[5] << 3) | (payload[6] >> 5)
        z_value = float(z_value_raw) * 0.05

        ref_temp_raw = ((payload[3] & 0x7F) << 6) | (payload[4] >> 2)
        ref_temp = float(ref_temp_raw) * 0.05

        d_value_raw = ((payload[1] & 0xF) << 9) | (payload[2] << 1) | (payload[3] >> 7)
        d_value = float(d_value_raw) * 0.05

        target_log_reduction_raw = ((payload[0] & 0xF) << 4) | (payload[1] >> 4)
        target_log_reduction = float(target_log_reduction_raw) * 0.1

        return cls(
            food_safe_mode=mode,
            product=product,
            serving=serving,
            selected_threshold_reference_temperature=threshold_ref_temp,
            z_value=z_value,
            reference_temperature=ref_temp,
            d_value_at_rt=d_value,
            target_log_reduction=target_log_reduction,
        )
