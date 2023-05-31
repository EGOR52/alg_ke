import datetime
import asyncio

import keadapter
from crud.algorithms.profit_increase_algorithm import ProfitIncreaseAlgorithm
from crud.bin import get_current_bin, get_max_profit_bin, get_optimal_bin, get_bin_by_number
from crud import get_shop_db, convert_product_db, get_competitors_db, get_nearest_delivery
from crud.algorithms.models import CheckResult
from crud.algorithms.sales_acceleration_algorithm import SalesAccelerationAlgorithm
from crud.timer_discount import get_product_timer_discount_conditions_db, get_timer_discount_db
from database import Bin, ProductsParticipationInCalendarEvent, TimerDiscount
from database.models import CalculationResult, Delivery, Competitor, ShopProduct, Shop, Product as ProductDb, \
    ResponsiblePerson

from sqlalchemy.orm import Session

from utils import dt


class AlgorithmDataForSku:
    def __init__(self, product_db: ProductDb, db: Session):
        self.competitors: list[Competitor] = asyncio.run(get_competitors_db(product_db.sku_id, db))
        self.current_bin: Bin = asyncio.run(get_current_bin(product_db, db))
        self.max_profit_bin: Bin = asyncio.run(get_max_profit_bin(product_db, db))
        self.nearest_delivery: Delivery = asyncio.run(get_nearest_delivery(product_db.sku_id, db))
        shop_product: ShopProduct = convert_product_db([product_db], product_db.shop, db)[0]
        self.result: CalculationResult = CalculationResult(shop=shop_product.shop,
                                                           product=shop_product.product,
                                                           error=False, path="", text="")
        self.timer_discount: TimerDiscount = asyncio.run(get_timer_discount_db(product_db.sku_id, db))
        self.timer_discount_condition = asyncio.run(get_product_timer_discount_conditions_db([product_db.sku_id], db))[0]

        # заглушка для цены бОльшей, чем бины
        if self.current_bin is None and product_db.last_price > product_db.min_price:
            BINS_QUANTYITY = 20
            self.current_bin: Bin = asyncio.run(get_bin_by_number(BINS_QUANTYITY, product_db, db))
            product_db.last_price = self.current_bin.to_value


class Algorithm:
    def __init__(self, shop_id: int, product_id: int, db: Session, sku_list: list[ProductDb] = None):
        super().__init__()
        self.product_id: int = product_id
        self.shop_id = shop_id
        self.db = db

        self.sku_list: list[ProductDb] = sku_list or self.db.query(ProductDb).filter(
            ProductDb.product_id == self.product_id).all()
        self.ran_for_product = False

        self.product_db: ProductDb
        self.product_db_data: AlgorithmDataForSku
        self.product_db_data_result_list: list[CalculationResult] = []

        self.sales_acceleration_algorithm: SalesAccelerationAlgorithm

    def init_sku(self, sku: ProductDb):
        self.product_db: ProductDb = sku
        self.product_db_data: AlgorithmDataForSku = AlgorithmDataForSku(self.product_db, self.db)
        self.sales_acceleration_algorithm: SalesAccelerationAlgorithm = SalesAccelerationAlgorithm(self)
        self.profit_increase_algorithm: ProfitIncreaseAlgorithm = ProfitIncreaseAlgorithm(self, self.sales_acceleration_algorithm)

    def run_by_sku_id(self, sku_id: int):
        for sku in self.sku_list:
            if sku.sku_id == sku_id:
                return self.run_for_sku(sku)

    def run_for_sku(self, sku):
        self.init_sku(sku)
        return self.run()

    def run_for_product(self):
        self.ran_for_product = True
        for sku in self.sku_list:
            self.product_db_data_result_list.append(self.run_for_sku(sku))
        return self.product_db_data_result_list

    def add_to_path(func):
        def wrapper(self, *args, **kwargs):
            result: CheckResult = func(self, *args, **kwargs)
            if result.path is not None:
                self.product_db_data.result.path += result.path
            if result.text is not None:
                self.product_db_data.result.text += result.text
            if result.full_text is not None:
                self.product_db_data.result.text = self.product_db_data.result.full_text
            return result.result

        return wrapper

    def validate(self, obj, fields_that_should_not_be_none: list):
        for field in fields_that_should_not_be_none:
            if getattr(obj, field) is None:
                self.product_db_data.result.error = True
                self.product_db_data.result.error_text = f"{field} is None"
                return False
        return True

    def validate_product_db(self):
        should_not_be_none = ["stock", "min_price", "last_price",
                              "days_without_sales", "top", "average_sales_speed", "min_sales_speed"]
        # заглушка для цены меньшей, чем бины
        if self.product_db.last_price < self.product_db.min_price:
            self.product_db_data.result.error = True
            self.product_db_data.result.error_text = f"Цена на продукт меньше минимальной цены! Примите меры {self.get_responsible_person_username()}"
            return False
        return self.validate(self.product_db, should_not_be_none)

    def validate_competitor(self, competitor: Competitor):
        return self.validate(competitor, ["average_sales_speed"])

    @add_to_path
    def is_status(self, status_title: str):
        if self.product_db.status_title == status_title:
            return CheckResult(path=f"Статус SKU = '{status_title}',", result=True)
        else:
            return CheckResult(path=f"Статус SKU ≠ '{status_title}',", result=False)

    @add_to_path
    def is_mark(self, value: str):
        if self.product_db.mark == value:
            return CheckResult(path=f"Метка = '{value}',", result=True)
        else:
            return CheckResult(path=f"Метка ≠ '{value}',", result=False)

    @add_to_path
    def is_bin_number(self, value: int):
        self.product_db_data.current_bin = self.product_db_data.current_bin or asyncio.run(
            get_current_bin(self.product_db, self.db))
        if self.product_db_data.current_bin.number == value:
            return CheckResult(path=f"Текущий бин продукта номер '{value}',", result=True)
        else:
            return CheckResult(path=f"Текущий бин продукта номер '{self.product_db_data.current_bin.number}',",
                               result=False)

    @add_to_path
    def is_active(self):
        if self.product_db.active:
            return CheckResult(path="Активен,", result=True)
        else:
            return CheckResult(path="НЕ активен,", result=False)

    @add_to_path
    def is_stock_empty(self):
        if self.product_db.stock == 0:
            return CheckResult(path="Stock = 0,", result=True)
        else:
            return CheckResult(path="Stock > 0,", result=False)

    @add_to_path
    def is_reserved_stock_empty(self):
        if self.product_db.reserved_stock == 0:
            return CheckResult(path="СДХ = 0,", result=True)
        else:
            return CheckResult(path="СДХ > 0,", result=False)

    @add_to_path
    def has_competitor_link(self):
        if len(self.product_db_data.competitors) > 0:
            return CheckResult(path="Есть ссылки на конкурентов,", result=True)
        else:
            return CheckResult(path="Нет ссылки на конкурентов,", result=False)

    @add_to_path
    def is_price_with_max_profit(self):
        self.product_db_data.max_profit_bin = asyncio.run(get_max_profit_bin(self.product_db, self.db))
        self.product_db_data.current_bin = asyncio.run(get_current_bin(self.product_db, self.db))
        if self.product_db_data.current_bin == self.product_db_data.max_profit_bin:
            return CheckResult(path="Максимальная прибыль,", result=True)
        else:
            return CheckResult(path="НЕ максимальная прибыль", result=False)

    @add_to_path
    def is_current_price__greater_than__min_price(self):
        if self.product_db.last_price >= self.product_db.min_price:
            return CheckResult(path="Нынешняя цена >= min цены,", result=True)
        else:
            return CheckResult(path="Нынешняя цена < min цены,", result=False)

    @add_to_path
    def is_sku_in_calendar_event(self):
        if self.product_db.on_calendar_event:
            return CheckResult(path="sku в распродаже,", result=True)
        else:
            return CheckResult(path="sku НЕ в распродаже, ", result=False)

    @add_to_path
    def is_sku_in_timer_discount(self):
        if self.product_db.on_timer_discount:
            return CheckResult(path="sku в скидке по таймеру,", result=True)
        else:
            # self.product_db_data.result.product.sku.price.new = self.product_db.min_price
            return CheckResult(path="sku НЕ в скидке по таймеру,", result=False)

    @add_to_path
    def is_days_without_sales__smaller_than__one(self):
        if self.product_db.days_without_sales < 1:
            return CheckResult(path="NOD < 1,", result=True)
        else:
            return CheckResult(path="NOD >= 1,", result=False)

    @add_to_path
    def is_min_price_border_reached(self):
        if self.product_db.min_price == self.product_db.last_price:
            return CheckResult(path="Достигнута min граница цены,", result=True)
        else:
            return CheckResult(path="НЕ достигнута min граница цены,", result=False)

    @add_to_path
    def is_days_without_sales__greater_than__three(self):
        if self.product_db.days_without_sales > 3:
            return CheckResult(path="NOD > 3", result=True)
        else:
            return CheckResult(path="NOD <= 3,", result=False)

    @add_to_path
    def is_top(self):
        if self.product_db.top:
            return CheckResult(path="Топ,", result=True)
        else:
            return CheckResult(path="Не топ,", result=False)

    @add_to_path
    def is_in_top100_search_results(self):
        found = True if self.product_db.search_position is not None and self.product_db.search_position != -1 else False
        if found:
            return CheckResult(path="В топ 100 поиска,", result=True)
        else:
            return CheckResult(path="НЕ в топ 100 поиска,", result=False)

    @add_to_path
    def is_avg_sales_speed__greater_than__min_sales_speed(self):
        if self.product_db.average_sales_speed > self.product_db.min_sales_speed:
            return CheckResult(path="Факт скорость продаж > min скорость продаж,", result=True)
        else:
            return CheckResult(path="Факт скорость продаж <= min скорость продаж,", result=False)

    @add_to_path
    def has_info_about_deliveries(self):
        self.nearest_delivery: Delivery = asyncio.run(get_nearest_delivery(self.product_db.sku_id, self.db))
        if self.nearest_delivery:
            return CheckResult(path="Есть инфо о поставках,", result=True)
        else:
            return CheckResult(path="Нет инфо о поставках,", result=False)

    @add_to_path
    def best_competitor_has_leftover_stock(self):
        if self.product_db_data.competitors[0].stock:
            return CheckResult(path="У лучшего конкурента НЕ пустые остатки,",
                               result=True)
        else:
            return CheckResult(path="У лучшего конкурента пустые остатки,",
                               result=False)


    @add_to_path
    def has_best_competitor_link_and_stock(self):
        if self.has_competitor_link() and self.best_competitor_has_leftover_stock():
            return CheckResult(path="ЕСТЬ ссылка на лучшего конкурента с низкой ценой и не пустыми остаткам skuid,",
                               result=True)
        else:
            return CheckResult(path="НЕТ ссылки на лучшего конкурента с низкой ценой и не пустыми остаткам skuid,",
                               result=False)

    @add_to_path
    def is_best_competitor_sales_speed__greater_than__our_sales_speed(self):
        if self.product_db.average_sales_speed < self.product_db_data.competitors[0].average_sales_speed:
            return CheckResult(path="Наша скорость продаж < скорости продаж конкурента,", result=True)
        else:
            return CheckResult(path="Наша скорость продаж >= скорости продаж конкурента,", result=False)

    @add_to_path
    def can_be_added_to_any_calendar_event(self):
        if p := self.product_db.most_suitable_calendar_event:
            return CheckResult(path=f"Может быть добавлена в календарную акцию с приоритетом {p.priority},",
                               result=True)
        else:
            return CheckResult(path=f"НЕ может быть добавлена ни в одну в календарную акцию,",
                               result=False)

    @add_to_path
    def is_price_for_calendar_event_calculated_for_every_sku_in_product(self):
        for product_db_data in self.product_db_data_result_list:
            if not product_db_data.product.sku.price.for_calendar_event:
                return CheckResult(path="НЕ для всех skuid одного prodid подсчитана цена,", result=False)
        return CheckResult(path="Для всех skuid одного prodid подсчитана цена,", result=True)

    def set_new_price(self, value: float):
        self.product_db_data.result.product.sku.price.new = value

    def set_new_price_for_product(self, value: float):
        for product_db_data in self.product_db_data_result_list:
            product_db_data.product.sku.price.new = value

    def set_new_calendar_event_price(self, value: float):
        self.product_db_data.result.product.sku.price.for_calendar_event = value

    def maximization_profit(self):
        self.product_db_data.max_profit_bin = asyncio.run(get_max_profit_bin(self.product_db, self.db))
        self.set_new_price(self.product_db_data.max_profit_bin.to_value)

    def minimization_overlap_oos_date_and_delivery_date(self):
        days = (datetime.date.today() - self.nearest_delivery.date).days
        optimal_sales_quantity_per_day = int(round(self.product_db.stock / days))
        self.product_db_data.max_profit_bin = asyncio.run(
            get_optimal_bin(self.product_db.sku_id, optimal_sales_quantity_per_day, self.db))
        self.maximization_profit()

    def set_bin_number(self, value: int):
        new_bin: Bin = asyncio.run(get_bin_by_number(value, self.product_db, self.db))
        self.set_new_price(new_bin.to_value)

    def increment_bin_number(self):
        self.set_bin_number(self.product_db_data.current_bin.number + 1)

    def decrement_bin_number(self):
        self.set_bin_number(self.product_db_data.current_bin.number - 1)

    def add_product_to_calendar_event(self):
        self.product_db_data.result.product.add_calendar_event_id_in_lk = self.product_db.most_suitable_calendar_event.calendar_event_id_in_lk

    def remove_product_from_calendar_event(self):
        self.product_db_data.result.product.remove_calendar_event_id_in_lk = self.product_db.involved_calendar_event.calendar_event_id_in_lk

    def add_sku_to_timer_discount(self, for_hours: int = 48):
        self.product_db_data.result.product.sku.add_to_timer_discount_for_hours = for_hours

    def remove_sku_from_timer_discount(self, discount_id: int):
        self.product_db_data.result.product.sku.remove_from_timer_discount_id = discount_id

    def set_mark(self, value: str):
        self.product_db.mark = value
        self.product_db_data.result.product.sku.mark = value

    def update_mark(self, value: str):
        self.product_db.mark += value
        self.product_db_data.result.product.sku.mark += value

    def send_message(self, message: str):
        pass

    def add_to_tasks(self, message: str):
        pass

    def add_to_logs(self, message: str):
        pass

    def set_update_price_datetime(self):
        pass

    def get_responsible_person_username(self):
        return f"{self.product_db.shop.responsible_person.username if self.product_db.shop.responsible_person else 'НЕ УКАЗАН ОТВЕТСТВЕННЫЙ'}"

    def run(self):
        if not self.validate_product_db():
            return self.product_db_data.result
        self.product_db.mark = ""
        if self.is_status("Заблокирован"):
            self.send_message(
                f"{self.product_db.sku_full_title} заблокирован {self.get_responsible_person_username()}")
            self.add_to_tasks(
                f"разобраться в блокировке товара {self.get_responsible_person_username()}")
            # self.add_to_logs("") КАКОЕ ДЕЙСТВИЕ???
            self.set_mark("1.1")
            self.product_db_data.result.text += (
                "1. Оповестить в чат о том, что skuid заблокирован с указанием ответственного за магазин\n"
                "2. Добавить в задачи разобраться в блокировке товара с указанием ответственного\n"
                "3. Отметить действие в таблице с логами\n"
                "4. Метка 1.1\n"
                "5. Переход к след СКУ\n"
            )
            self.set_new_price(None)
        else:
            if self.is_active():
                if self.is_stock_empty():
                    if self.is_reserved_stock_empty():
                        if self.can_be_added_to_any_calendar_event():
                            self.set_new_calendar_event_price(self.product_db.most_suitable_calendar_event.recommended_price)
                            if self.is_price_for_calendar_event_calculated_for_every_sku_in_product():
                                self.product_db_data.result.text += "Вставляем в распродажу весь продукт"
                                self.add_product_to_calendar_event()
                                self.set_mark("1.10B")
                            else:
                                self.product_db_data.result.text += "Переходим к подсчетам для следующего skuid, относящего к одному prodid"
                        else:
                            if self.is_bin_number(15):
                                self.product_db_data.result.text += "Переходим к подсчетам для следующего skuid, относящего к одному prodid"
                            else:
                                """
                                1. Поставить цену 15 бина (если считать снизу)  в день
                                2. Отметить дату обновления цены
                                3. Отметить действие в таблице с логами
                                4. Оповестить в чат о действии
                                """
                                self.set_bin_number(15)
                                self.product_db_data.result.text += "Поставить цену 15 бина (если считать снизу)  в день"
                                self.set_mark("1.3")
                    else:
                        self.product_db_data.result.text += "Есть необходимость пополнения товара с СДХ (склад длительного хранения)"
                        self.set_mark("1.4")
                else:
                    if self.is_status("В продаже"):
                        if self.is_current_price__greater_than__min_price():
                            if self.is_days_without_sales__smaller_than__one():
                                if self.is_avg_sales_speed__greater_than__min_sales_speed():
                                    # self.price_change_algorithm.run()
                                    # TODO: запуск 3 алгоритма вместо поднятия цены на один бин
                                    self.product_db_data.result.text += "Меняем цену согласно алгоритму #3\n"
                                    self.profit_increase_algorithm.run()
                                else:

                                    self.product_db_data.result.text += "Меняем цену, согласно алгоритму #2\n"
                                    self.sales_acceleration_algorithm.run()
                            else:
                                if self.is_min_price_border_reached():
                                    if self.is_days_without_sales__greater_than__three():
                                        self.send_message(
                                            f"{self.product_db.sku_full_title} не продается уже {self.product_db.days_without_sales} дней,  ключевик '{self.product_db.search_key}', позиция {self.product_db.search_position} {self.get_responsible_person_username()}\n")
                                        self.add_to_logs("")
                                        self.add_to_tasks("Прокачать/Найти причину отсутствия продаж для skuid")
                                        self.set_mark("1.9")
                                        self.product_db_data.result.text += (
                                            "1. Критическое оповещение в чате со списком всех skuid, о том, что\n"
                                            "Skuid не продается уже ? дней,  ключевик 'Лубрикант', позиция 12 с отметкой управляющего магазина\n"
                                            "2. Отметить действие в таблице с логами\n"
                                            "3. Добавить в задачи 'Прокачать/Найти причину отсутствия продаж для skuid'\n"
                                            "4. Метка 1.9\n")
                                    else:
                                        if self.is_top():
                                            if self.is_in_top100_search_results():
                                                self.send_message(
                                                    f"ТОП товар {self.product_db.sku_full_title} не продается уже {self.product_db.days_without_sales} дней {self.get_responsible_person_username()}\n")
                                                self.add_to_logs("")
                                                self.add_to_tasks(
                                                    f"Найти причину отсутствия продаж для {self.product_db.sku_full_title}")
                                                self.set_mark("1.11")
                                                self.product_db_data.result.text += (
                                                    "1. Критическое оповещение в чат с отметкой управляющего и меня, что 'ТОП товар skuid не продается уже ? дней'\n"
                                                    "2. Отметить действие в таблице с логами\n"
                                                    "3. Добавить в задачи 'Найти причину отсутствия продаж для skuid'\n"
                                                    "4. Метка 1.11\n"
                                                )
                                            else:
                                                if self.is_in_top100_search_results():
                                                    self.send_message(
                                                        f"ТОП товар {self.product_db.sku_full_title} нуждается в прокачке {self.get_responsible_person_username()}\n")
                                                    self.add_to_logs("")
                                                    self.add_to_tasks(
                                                        f"Необходимо прокачать отзывами {self.product_db.sku_full_title}")
                                                    self.set_mark("1.10")
                                                self.product_db_data.result.text += (
                                                    "1. Оповещение в чат с отметкой управляющего, что ТОП нуждается в прокачке\n"
                                                    "2. Отметить действие в таблице с логами\n"
                                                    "3. Добавить в задачи 'Необходимо прокачать отзывами skuid'\n"
                                                    "4. Метка 1.10\n"
                                                )
                                            self.product_db_data.result.text += "Переход к след СКУ"
                                            self.set_new_price(None)
                                        else:
                                            self.product_db_data.result.text += "Переход к след СКУ"
                                            self.set_new_price(None)
                                else:
                                    if self.is_top():
                                        self.send_message(
                                            f"ТОП товар {self.product_db.sku_full_title} не продаётся {self.get_responsible_person_username()}\n")
                                        self.add_to_logs("")
                                        self.product_db_data.result.text += (
                                            "1. Оповещаем в чат, что ТОП товар не продается\n"
                                            "2. Отметить действие в таблице с логами\n")
                                    self.product_db_data.result.text += "Понижаем цену, согласно алгоритму #2:\n"
                                    self.sales_acceleration_algorithm.run()
            else:
                self.set_mark("1.2")
                self.product_db_data.result.text += ("1. Переходим к след SKU\n"
                                                     "2. Метка 1.2\n")
                self.set_new_price(None)
        return self.product_db_data.result

        #     if self.is_price_with_max_profit():
        #         pass
        #     else:
        #         self.maximization_profit()
        #     return self.result
        # else:
        #     if self.is_current_price_greater_than_min_price():
        #         if self.is_days_without_sales_greater_than_one():
        #             if self.is_min_price_border_reached():
        #                 if self.is_days_without_sales_greater_than_three():
        #                     return self.result
        #                 else:
        #                     if self.is_top(text={False: "Ничего не требуется"}):
        #                         if self.is_in_top100search_results():
        #                             pass
        #                     return self.result
        #             else:
        #                 if self.is_top(text={True: "1. Оповещаем в чат, что ТОП товар не продается\n"
        #                                            "2. Отметить действие в таблице с логами"
        #                                            "Понижаем цену, согласно алгоритму #1",
        #                                      False: "Понижаем цену, согласно алгоритму #1"}):
        #                     self.price_change_algorithm.run()
        #                     return self.result
        #                 else:
        #                     self.price_change_algorithm.run()
        #                     return self.result
        #         else:
        #             if self.is_avg_sales_speed_greater_than_min_sales_speed():
        #                 if self.has_info_about_deliveries():
        #                     self.minimization_overlap_oos_date_and_delivery_date()
        #                 else:
        #                     self.maximization_profit()
        #             else:
        #                 self.price_change_algorithm.run()
        #             if self.has_competitor_link():
        #                 self.validate_competitor(self.competitors[0])
        #                 if self.is_best_competitor_sales_speed_greater_than_our_sales_speed():
        #                     # Демпинг быстрее (ЧТО ЗНАЧИТ)
        #                     return self.result
        #                 else:
        #                     # Демпинг медленнее (ЧТО ЗНАЧИТ)
        #                     return self.result
        #             else:
        #                 self.maximization_profit()
        #                 return self.result
        #     else:
        #         if self.is_sku_in_calendar_event():
        #             pass
        #         else:
        #             if self.is_sku_in_timer_discount():
        #                 pass
        #         return self.result
