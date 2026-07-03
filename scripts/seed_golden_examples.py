"""Seed golden examples into core/knowledge_graph/golden_examples/.

Standalone script — no aether_os imports required.
Run: python3 scripts/seed_golden_examples.py
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path

OUT = Path(__file__).parent.parent / "core" / "knowledge_graph" / "golden_examples"
OUT.mkdir(parents=True, exist_ok=True)

NOW = datetime.utcnow().strftime("%Y-%m-%d")


def _file(domain: str, examples: list[dict]) -> None:
    path = OUT / f"{domain}.json"
    path.write_text(json.dumps({"domain": domain, "version": "1.0", "generated_at": NOW, "examples": examples}, indent=2))
    print(f"  {path.name}: {len(examples)} examples")


# ── helpers ────────────────────────────────────────────────────────────────────

def _ex(idx: int, domain: str, description: str, entities: list[dict], endpoints: list[str],
        integrations: list[str] = None, features: list[str] = None, tags: list[str] = None) -> dict:
    return {
        "id": f"{domain[:4]}_{idx:03d}",
        "type": "app_description_to_domain_ir",
        "input": description,
        "output": {
            "domain": domain,
            "entities": entities,
            "api_endpoints": endpoints,
            "integrations": integrations or [],
            "features": features or ["auth", "crud"],
        },
        "tags": tags or [domain],
        "quality_score": 1.0,
    }


def _e(name: str, *fields) -> dict:
    """Shorthand entity builder."""
    flist = []
    for i, f in enumerate(fields):
        if isinstance(f, str):
            parts = f.split(":")
            fname = parts[0]
            ftype = parts[1] if len(parts) > 1 else "str"
            fld = {"name": fname, "type": ftype}
            if fname == "id":
                fld["primary_key"] = True
            if ftype.startswith("fk_"):
                fld["type"] = "int"
                fld["foreign_key"] = ftype[3:]
            if fname in ("email", "slug", "username", "phone", "sku", "code"):
                fld["unique"] = True
            if fname in ("image_url", "avatar_url", "description", "notes", "bio"):
                fld["nullable"] = True
            if ftype == "enum":
                fld["values"] = parts[2].split(",") if len(parts) > 2 else ["active", "inactive"]
            flist.append(fld)
    return {"name": name, "fields": flist}


# ── ECOMMERCE ──────────────────────────────────────────────────────────────────

_ecommerce = [
    _ex(1, "ecommerce", "Online store for handmade jewelry with product listings, shopping cart, and Stripe checkout",
        [_e("Product","id:int","name","price:decimal","stock_qty:int","image_url","category"),
         _e("Order","id:int","user_id:fk_User.id","total:decimal","status:enum:pending,paid,shipped,delivered","created_at:datetime"),
         _e("CartItem","id:int","user_id:fk_User.id","product_id:fk_Product.id","quantity:int")],
        ["/products","/products/{id}","/cart","/orders","/checkout"],["stripe"],["auth","cart","checkout","order_tracking"]),
    _ex(2, "ecommerce", "B2B wholesale catalog with tiered pricing, bulk ordering, and credit terms",
        [_e("Product","id:int","sku","name","unit_price:decimal","min_order_qty:int","category"),
         _e("Pricetier","id:int","product_id:fk_Product.id","min_qty:int","price:decimal","customer_tier:enum:bronze,silver,gold"),
         _e("Order","id:int","org_id:fk_Org.id","status:enum:draft,submitted,approved,shipped","total:decimal","payment_terms:str"),
         _e("OrderLine","id:int","order_id:fk_Order.id","product_id:fk_Product.id","qty:int","unit_price:decimal")],
        ["/products","/orders","/orders/{id}/lines","/pricing"],["stripe"],["auth","bulk_ordering","tiered_pricing"]),
    _ex(3, "ecommerce", "Digital downloads store for fonts, templates, and design assets with instant delivery",
        [_e("Product","id:int","name","slug","price:decimal","file_url","preview_url","downloads_count:int"),
         _e("Purchase","id:int","user_id:fk_User.id","product_id:fk_Product.id","payment_id","download_token","expires_at:datetime"),
         _e("Review","id:int","product_id:fk_Product.id","user_id:fk_User.id","rating:int","body","created_at:datetime")],
        ["/products","/purchase","/downloads/{token}","/reviews"],[],["auth","instant_delivery","download_tracking"]),
    _ex(4, "ecommerce", "Monthly subscription box for artisan coffee with preferences and pause/resume",
        [_e("Plan","id:int","name","price_monthly:decimal","beans_count:int","grind_type:enum:whole,coarse,medium,fine"),
         _e("Subscription","id:int","user_id:fk_User.id","plan_id:fk_Plan.id","status:enum:active,paused,cancelled","next_billing:datetime"),
         _e("Shipment","id:int","subscription_id:fk_Subscription.id","tracking_no","shipped_at:datetime","delivered_at:datetime")],
        ["/plans","/subscriptions","/subscriptions/{id}/pause","/shipments"],["stripe"],["auth","subscriptions","shipping"]),
    _ex(5, "ecommerce", "Online auction platform with real-time bidding, reserve prices, and auto-extend",
        [_e("Auction","id:int","title","description","start_price:decimal","reserve_price:decimal","ends_at:datetime","status:enum:draft,live,ended"),
         _e("Bid","id:int","auction_id:fk_Auction.id","user_id:fk_User.id","amount:decimal","created_at:datetime"),
         _e("AuctionImage","id:int","auction_id:fk_Auction.id","url","is_primary:bool")],
        ["/auctions","/auctions/{id}/bid","/auctions/{id}/bids"],["stripe"],["auth","realtime","bidding"]),
    _ex(6, "ecommerce", "Camera and lens rental marketplace with calendar availability and damage deposits",
        [_e("Equipment","id:int","name","brand","model","daily_rate:decimal","deposit:decimal","condition:enum:excellent,good,fair"),
         _e("Rental","id:int","equipment_id:fk_Equipment.id","user_id:fk_User.id","start_date:datetime","end_date:datetime","status:enum:pending,confirmed,active,returned","total:decimal"),
         _e("Availability","id:int","equipment_id:fk_Equipment.id","date:datetime","is_available:bool")],
        ["/equipment","/rentals","/rentals/{id}","/availability"],["stripe"],["auth","calendar","rentals"]),
    _ex(7, "ecommerce", "Print-on-demand platform for custom t-shirts with design upload and Printful fulfillment",
        [_e("Product","id:int","name","base_price:decimal","sizes:json","colors:json"),
         _e("Design","id:int","user_id:fk_User.id","name","file_url","preview_url","status:enum:pending,approved,rejected"),
         _e("Order","id:int","user_id:fk_User.id","status:enum:pending,printing,shipped","total:decimal","printful_order_id"),
         _e("OrderItem","id:int","order_id:fk_Order.id","product_id:fk_Product.id","design_id:fk_Design.id","size","color","qty:int")],
        ["/products","/designs","/orders","/orders/{id}"],["stripe","printful"],["auth","design_upload","fulfillment"]),
    _ex(8, "ecommerce", "Farmers market online store with local pickup slots and seasonal product availability",
        [_e("Farm","id:int","name","slug","location","bio"),
         _e("Product","id:int","farm_id:fk_Farm.id","name","price:decimal","unit","stock_qty:int","season:enum:spring,summer,autumn,winter,year_round"),
         _e("PickupSlot","id:int","date:datetime","location","capacity:int","booked:int"),
         _e("Order","id:int","user_id:fk_User.id","pickup_slot_id:fk_PickupSlot.id","total:decimal","status:enum:pending,confirmed,ready,collected")],
        ["/farms","/products","/pickup-slots","/orders"],["stripe"],["auth","local_pickup","seasonal"]),
    _ex(9, "ecommerce", "Sneaker resale marketplace with authentication verification and price history",
        [_e("Listing","id:int","seller_id:fk_User.id","brand","model","size","condition:enum:new,like_new,used","asking_price:decimal","status:enum:active,sold,removed"),
         _e("Offer","id:int","listing_id:fk_Listing.id","buyer_id:fk_User.id","amount:decimal","status:enum:pending,accepted,declined"),
         _e("PriceHistory","id:int","brand","model","size","sale_price:decimal","sold_at:datetime"),
         _e("AuthRequest","id:int","listing_id:fk_Listing.id","status:enum:pending,authentic,rejected","notes")],
        ["/listings","/listings/{id}/offer","/price-history","/auth-requests"],["stripe"],["auth","authentication","price_tracking"]),
    _ex(10, "ecommerce", "Wine club with sommelier-curated monthly boxes and tasting notes",
        [_e("Wine","id:int","name","producer","vintage:int","region","varietal","score:decimal","price:decimal"),
         _e("Box","id:int","name","month:str","description","price:decimal"),
         _e("BoxWine","id:int","box_id:fk_Box.id","wine_id:fk_Wine.id","quantity:int"),
         _e("Subscription","id:int","user_id:fk_User.id","tier:enum:red,white,mixed,premium","status:enum:active,paused","next_ship:datetime")],
        ["/wines","/boxes","/subscriptions","/tasting-notes"],["stripe"],["auth","subscriptions","curation"]),
    _ex(11,"ecommerce","Online bookstore with reading lists, wishlists, and staff picks",
        [_e("Book","id:int","isbn","title","author","publisher","price:decimal","stock:int","genre"),
         _e("ReadingList","id:int","user_id:fk_User.id","name","is_public:bool"),
         _e("ReadingListBook","id:int","list_id:fk_ReadingList.id","book_id:fk_Book.id","order_index:int"),
         _e("Order","id:int","user_id:fk_User.id","total:decimal","status:enum:pending,processing,shipped")],
        ["/books","/reading-lists","/orders","/staff-picks"],["stripe"],["auth","wishlist","recommendations"]),
    _ex(12,"ecommerce","Pet supplies store with subscription autoship and vet diet recommendations",
        [_e("Product","id:int","name","brand","pet_type:enum:dog,cat,bird,fish,reptile","price:decimal","stock:int"),
         _e("AutoShip","id:int","user_id:fk_User.id","product_id:fk_Product.id","frequency_days:int","next_ship:datetime","status:enum:active,paused"),
         _e("Pet","id:int","owner_id:fk_User.id","name","species","breed","weight_kg:decimal","birth_date:datetime"),
         _e("VetRecommendation","id:int","pet_id:fk_Pet.id","product_id:fk_Product.id","notes")],
        ["/products","/autoship","/pets","/recommendations"],["stripe"],["auth","subscriptions","pet_profiles"]),
    _ex(13,"ecommerce","Handmade crafts marketplace where artisans sell directly to buyers",
        [_e("Shop","id:int","owner_id:fk_User.id","name","slug","bio","location","banner_url"),
         _e("Product","id:int","shop_id:fk_Shop.id","name","price:decimal","stock:int","materials","processing_days:int"),
         _e("Order","id:int","buyer_id:fk_User.id","seller_id:fk_User.id","status:enum:pending,paid,shipped,complete","total:decimal"),
         _e("Review","id:int","product_id:fk_Product.id","buyer_id:fk_User.id","rating:int","body")],
        ["/shops","/products","/orders","/reviews"],["stripe"],["auth","marketplace","seller_portal"]),
    _ex(14,"ecommerce","Furniture store with AR room preview, custom dimensions, and white-glove delivery",
        [_e("Product","id:int","name","category","material","price:decimal","lead_days:int","ar_model_url","dimensions:json"),
         _e("CustomOrder","id:int","product_id:fk_Product.id","user_id:fk_User.id","custom_dimensions:json","custom_finish","price:decimal","status:enum:quote,confirmed,producing,shipped"),
         _e("DeliverySlot","id:int","date:datetime","slots_available:int"),
         _e("Order","id:int","user_id:fk_User.id","delivery_slot_id:fk_DeliverySlot.id","total:decimal","status:enum:pending,confirmed,delivered")],
        ["/products","/custom-orders","/delivery-slots","/orders"],["stripe"],["auth","custom_orders","scheduling"]),
    _ex(15,"ecommerce","Sports equipment rental for ski resorts with size fitting and damage waiver",
        [_e("Equipment","id:int","type:enum:ski,snowboard,boots,helmet,poles","brand","size","daily_rate:decimal","status:enum:available,rented,maintenance"),
         _e("Rental","id:int","user_id:fk_User.id","equipment_id:fk_Equipment.id","start_date:datetime","end_date:datetime","total:decimal","waiver_signed:bool"),
         _e("FitProfile","id:int","user_id:fk_User.id","height_cm:int","weight_kg:int","boot_size:decimal","skill_level:enum:beginner,intermediate,advanced")],
        ["/equipment","/rentals","/fit-profiles","/availability"],["stripe"],["auth","rentals","fitting"]),
]

# ── HEALTHCARE ─────────────────────────────────────────────────────────────────

_healthcare = [
    _ex(1,"healthcare","Patient management system for a multi-doctor family practice clinic",
        [_e("Patient","id:int","mrn","first_name","last_name","dob:datetime","gender:enum:male,female,other","phone","email"),
         _e("Appointment","id:int","patient_id:fk_Patient.id","doctor_id:fk_User.id","scheduled_at:datetime","duration_min:int","status:enum:scheduled,completed,cancelled","notes"),
         _e("VitalSign","id:int","patient_id:fk_Patient.id","recorded_at:datetime","bp_systolic:int","bp_diastolic:int","pulse:int","temp_c:decimal","weight_kg:decimal")],
        ["/patients","/appointments","/vitals","/patients/{id}/history"],[],"auth,patient_records,scheduling".split(",")),
    _ex(2,"healthcare","Telemedicine platform with video consultations, e-prescriptions, and follow-ups",
        [_e("Consultation","id:int","patient_id:fk_Patient.id","doctor_id:fk_User.id","scheduled_at:datetime","video_room_id","status:enum:upcoming,in_progress,completed","duration_min:int"),
         _e("Prescription","id:int","consultation_id:fk_Consultation.id","medication","dosage","frequency","duration_days:int","refills:int"),
         _e("FollowUp","id:int","consultation_id:fk_Consultation.id","due_date:datetime","notes","completed:bool")],
        ["/consultations","/consultations/{id}/join","/prescriptions","/follow-ups"],["twilio"],["auth","video","prescriptions"]),
    _ex(3,"healthcare","Pharmacy inventory and dispensing system with drug interaction alerts",
        [_e("Drug","id:int","ndc","name","generic_name","manufacturer","form:enum:tablet,capsule,liquid,injection","strength","controlled:bool"),
         _e("Inventory","id:int","drug_id:fk_Drug.id","lot_no","expiry:datetime","qty_on_hand:int","reorder_level:int","unit_cost:decimal"),
         _e("Dispense","id:int","prescription_id:fk_Prescription.id","drug_id:fk_Drug.id","qty:int","dispensed_by:fk_User.id","dispensed_at:datetime"),
         _e("DrugInteraction","id:int","drug_a_id:fk_Drug.id","drug_b_id:fk_Drug.id","severity:enum:minor,moderate,major","description")],
        ["/drugs","/inventory","/dispense","/interactions"],[],"auth,dispensing,alerts".split(",")),
    _ex(4,"healthcare","Mental health tracker with mood journaling, therapy session booking, and progress charts",
        [_e("MoodLog","id:int","user_id:fk_User.id","logged_at:datetime","mood_score:int","energy:int","anxiety:int","notes"),
         _e("TherapySession","id:int","patient_id:fk_User.id","therapist_id:fk_User.id","scheduled_at:datetime","type:enum:individual,group,cbt","notes","status:enum:upcoming,completed,cancelled"),
         _e("Goal","id:int","user_id:fk_User.id","title","target_date:datetime","status:enum:active,achieved","category:enum:sleep,anxiety,mood,relationships")],
        ["/mood-logs","/sessions","/goals","/progress"],[],"auth,journaling,scheduling".split(",")),
    _ex(5,"healthcare","Lab results portal where patients view test results with reference ranges",
        [_e("LabOrder","id:int","patient_id:fk_Patient.id","ordered_by:fk_User.id","ordered_at:datetime","status:enum:ordered,collected,processing,resulted"),
         _e("LabTest","id:int","name","code","category","units","ref_range_low:decimal","ref_range_high:decimal"),
         _e("LabResult","id:int","order_id:fk_LabOrder.id","test_id:fk_LabTest.id","value:decimal","status:enum:normal,low,high,critical","resulted_at:datetime")],
        ["/lab-orders","/lab-results","/patients/{id}/labs"],[],"auth,lab_results,notifications".split(",")),
    _ex(6,"healthcare","Dental practice management with treatment plans, X-ray storage, and insurance claims",
        [_e("Patient","id:int","first_name","last_name","dob:datetime","insurance_provider","insurance_id"),
         _e("TreatmentPlan","id:int","patient_id:fk_Patient.id","created_by:fk_User.id","status:enum:draft,approved,in_progress,complete"),
         _e("TreatmentItem","id:int","plan_id:fk_TreatmentPlan.id","tooth_no:int","procedure_code","description","cost:decimal","status:enum:planned,completed"),
         _e("InsuranceClaim","id:int","patient_id:fk_Patient.id","items:json","submitted_at:datetime","status:enum:pending,approved,denied","approved_amount:decimal")],
        ["/patients","/treatment-plans","/claims","/xrays"],[],"auth,treatment_planning,insurance".split(",")),
    _ex(7,"healthcare","Vaccination record system for schools with parent consent and reminder notifications",
        [_e("Student","id:int","first_name","last_name","dob:datetime","school_id:fk_School.id","grade","parent_email"),
         _e("Vaccine","id:int","name","manufacturer","doses_required:int","schedule_months:json"),
         _e("VaccinationRecord","id:int","student_id:fk_Student.id","vaccine_id:fk_Vaccine.id","dose_no:int","administered_at:datetime","lot_no","administered_by"),
         _e("ConsentForm","id:int","student_id:fk_Student.id","vaccine_id:fk_Vaccine.id","consented:bool","signed_at:datetime","guardian_name")],
        ["/students","/vaccines","/records","/consent-forms"],["sendgrid"],"auth,consent,notifications".split(",")),
    _ex(8,"healthcare","Hospital bed management system with real-time occupancy and transfer requests",
        [_e("Ward","id:int","name","floor:int","bed_count:int","specialty:enum:general,icu,pediatric,maternity,surgical"),
         _e("Bed","id:int","ward_id:fk_Ward.id","bed_no","status:enum:available,occupied,cleaning,maintenance"),
         _e("Admission","id:int","patient_id:fk_Patient.id","bed_id:fk_Bed.id","admitted_at:datetime","discharged_at:datetime","diagnosis","attending_id:fk_User.id"),
         _e("TransferRequest","id:int","admission_id:fk_Admission.id","from_ward_id:fk_Ward.id","to_ward_id:fk_Ward.id","reason","status:enum:pending,approved,completed")],
        ["/wards","/beds","/admissions","/transfers"],[],"auth,bed_management,realtime".split(",")),
    _ex(9,"healthcare","Sports medicine clinic with injury tracking, rehab plans, and athlete performance",
        [_e("Athlete","id:int","user_id:fk_User.id","sport","team","position","date_of_birth:datetime"),
         _e("Injury","id:int","athlete_id:fk_Athlete.id","body_part","injury_type","severity:enum:mild,moderate,severe","injured_at:datetime","return_date:datetime"),
         _e("RehabExercise","id:int","name","description","video_url","target_area","sets:int","reps:int","duration_sec:int"),
         _e("RehabSession","id:int","injury_id:fk_Injury.id","scheduled_at:datetime","exercises:json","pain_score:int","notes")],
        ["/athletes","/injuries","/rehab-plans","/sessions"],[],"auth,injury_tracking,rehab".split(",")),
    _ex(10,"healthcare","Home care coordination platform for elderly patients with caregiver scheduling",
        [_e("Client","id:int","first_name","last_name","dob:datetime","address","emergency_contact","care_level:enum:basic,intermediate,intensive"),
         _e("Caregiver","id:int","user_id:fk_User.id","certifications:json","availability:json","hourly_rate:decimal"),
         _e("Visit","id:int","client_id:fk_Client.id","caregiver_id:fk_Caregiver.id","scheduled_at:datetime","duration_hours:decimal","tasks:json","status:enum:scheduled,in_progress,completed","notes"),
         _e("CareLog","id:int","visit_id:fk_Visit.id","vital_signs:json","medications_given:json","concerns")],
        ["/clients","/caregivers","/visits","/care-logs"],["sendgrid","twilio"],"auth,scheduling,care_coordination".split(",")),
    _ex(11,"healthcare","Weight loss clinic with meal planning, progress tracking, and coach check-ins",
        [_e("Client","id:int","user_id:fk_User.id","start_weight:decimal","goal_weight:decimal","height_cm:int","program:enum:standard,keto,mediterranean,intermittent_fasting"),
         _e("WeightLog","id:int","client_id:fk_Client.id","logged_at:datetime","weight_kg:decimal","body_fat_pct:decimal","notes"),
         _e("MealPlan","id:int","client_id:fk_Client.id","week_start:datetime","meals:json","calories_target:int","protein_g:int"),
         _e("CoachNote","id:int","client_id:fk_Client.id","coach_id:fk_User.id","created_at:datetime","body","follow_up_date:datetime")],
        ["/clients","/weight-logs","/meal-plans","/coach-notes"],[],"auth,progress_tracking,coaching".split(",")),
    _ex(12,"healthcare","Blood bank management with donor tracking, inventory, and compatibility checks",
        [_e("Donor","id:int","first_name","last_name","blood_type:enum:A+,A-,B+,B-,AB+,AB-,O+,O-","last_donation:datetime","eligible:bool"),
         _e("Donation","id:int","donor_id:fk_Donor.id","donated_at:datetime","volume_ml:int","unit_no","status:enum:collected,tested,available,used,discarded"),
         _e("BloodRequest","id:int","patient_id:fk_Patient.id","blood_type:enum:A+,A-,B+,B-,AB+,AB-,O+,O-","units_needed:int","urgency:enum:routine,urgent,emergency","status:enum:pending,fulfilled"),
         _e("CrossMatch","id:int","request_id:fk_BloodRequest.id","donation_id:fk_Donation.id","result:enum:compatible,incompatible")],
        ["/donors","/donations","/blood-requests","/cross-matches"],[],"auth,inventory,compatibility".split(",")),
    _ex(13,"healthcare","Physiotherapy clinic with exercise videos, home program assignment, and outcome tracking",
        [_e("Patient","id:int","first_name","last_name","diagnosis","referring_doctor"),
         _e("Exercise","id:int","name","description","video_url","difficulty:enum:easy,medium,hard","target_area","sets:int","reps:int"),
         _e("HomeProgram","id:int","patient_id:fk_Patient.id","therapist_id:fk_User.id","exercises:json","start_date:datetime","review_date:datetime"),
         _e("OutcomeMeasure","id:int","patient_id:fk_Patient.id","scale_name","score:decimal","recorded_at:datetime")],
        ["/patients","/exercises","/home-programs","/outcomes"],[],"auth,exercise_library,home_programs".split(",")),
    _ex(14,"healthcare","Medical education LMS for residency programs with case libraries and assessments",
        [_e("ClinicalCase","id:int","title","specialty","difficulty:enum:novice,intermediate,advanced","presentation","diagnosis","learning_points:json","created_by:fk_User.id"),
         _e("Assessment","id:int","case_id:fk_ClinicalCase.id","resident_id:fk_User.id","answers:json","score:decimal","completed_at:datetime","faculty_feedback"),
         _e("Competency","id:int","name","domain","description"),
         _e("ResidentProgress","id:int","resident_id:fk_User.id","competency_id:fk_Competency.id","level:enum:novice,developing,competent,proficient","evidence:json")],
        ["/cases","/assessments","/competencies","/progress"],[],"auth,case_library,assessments".split(",")),
    _ex(15,"healthcare","Occupational health program for employers with work injury tracking and fitness-for-duty assessments",
        [_e("Employee","id:int","employee_id","first_name","last_name","department","job_title","hire_date:datetime"),
         _e("WorkInjury","id:int","employee_id:fk_Employee.id","injury_date:datetime","body_part","mechanism","lost_time_days:int","status:enum:open,medical_only,lost_time,closed"),
         _e("FitnessDetermination","id:int","employee_id:fk_Employee.id","assessed_by:fk_User.id","assessed_at:datetime","result:enum:fit,fit_with_restrictions,unfit","restrictions:json","review_date:datetime"),
         _e("HealthSurveillance","id:int","employee_id:fk_Employee.id","type","due_date:datetime","completed_at:datetime","findings")],
        ["/employees","/injuries","/fitness-determinations","/surveillance"],[],"auth,injury_tracking,compliance".split(",")),
]

# ── FINTECH ────────────────────────────────────────────────────────────────────

_fintech = [
    _ex(1,"fintech","Personal expense tracker with bank sync, budget envelopes, and spending insights",
        [_e("Account","id:int","user_id:fk_User.id","name","type:enum:checking,savings,credit,cash","balance:decimal","currency"),
         _e("Transaction","id:int","account_id:fk_Account.id","amount:decimal","category","merchant","date:datetime","notes"),
         _e("Budget","id:int","user_id:fk_User.id","category","monthly_limit:decimal","month:str")],
        ["/accounts","/transactions","/budgets","/insights"],[],"auth,bank_sync,budgeting".split(",")),
    _ex(2,"fintech","Invoice management for freelancers with time tracking, auto-reminders, and PDF export",
        [_e("Client","id:int","user_id:fk_User.id","name","email","company","tax_id","address"),
         _e("Invoice","id:int","client_id:fk_Client.id","number","issue_date:datetime","due_date:datetime","total:decimal","status:enum:draft,sent,paid,overdue"),
         _e("InvoiceItem","id:int","invoice_id:fk_Invoice.id","description","qty:decimal","rate:decimal","amount:decimal"),
         _e("TimeEntry","id:int","user_id:fk_User.id","client_id:fk_Client.id","date:datetime","hours:decimal","description","invoiced:bool")],
        ["/clients","/invoices","/time-entries","/invoices/{id}/pdf"],["sendgrid","stripe"],"auth,invoicing,time_tracking".split(",")),
    _ex(3,"fintech","Crypto portfolio tracker with live prices, P&L calculation, and tax lot tracking",
        [_e("Asset","id:int","symbol","name","coingecko_id"),
         _e("Holding","id:int","user_id:fk_User.id","asset_id:fk_Asset.id","quantity:decimal","avg_cost:decimal"),
         _e("Trade","id:int","user_id:fk_User.id","asset_id:fk_Asset.id","type:enum:buy,sell","quantity:decimal","price:decimal","fee:decimal","traded_at:datetime","exchange"),
         _e("PriceSnapshot","id:int","asset_id:fk_Asset.id","price_usd:decimal","market_cap:decimal","recorded_at:datetime")],
        ["/assets","/holdings","/trades","/portfolio/pnl"],[],"auth,portfolio,price_tracking".split(",")),
    _ex(4,"fintech","Small business accounting with chart of accounts, journal entries, and P&L reports",
        [_e("Account","id:int","code","name","type:enum:asset,liability,equity,revenue,expense","parent_id:fk_Account.id","balance:decimal"),
         _e("JournalEntry","id:int","date:datetime","description","reference","created_by:fk_User.id","posted:bool"),
         _e("JournalLine","id:int","entry_id:fk_JournalEntry.id","account_id:fk_Account.id","debit:decimal","credit:decimal","memo"),
         _e("FiscalPeriod","id:int","name","start_date:datetime","end_date:datetime","closed:bool")],
        ["/accounts","/journal-entries","/reports/profit-loss","/reports/balance-sheet"],[],"auth,accounting,reporting".split(",")),
    _ex(5,"fintech","Payroll system with salary bands, deductions, tax withholding, and payslip generation",
        [_e("Employee","id:int","first_name","last_name","tax_id","salary:decimal","pay_frequency:enum:weekly,biweekly,monthly","bank_account"),
         _e("PayRun","id:int","period_start:datetime","period_end:datetime","status:enum:draft,approved,paid","total_gross:decimal","total_net:decimal"),
         _e("PaySlip","id:int","pay_run_id:fk_PayRun.id","employee_id:fk_Employee.id","gross:decimal","deductions:json","net:decimal","paid_at:datetime"),
         _e("Deduction","id:int","name","type:enum:tax,insurance,pension,other","calculation:enum:fixed,percentage","value:decimal")],
        ["/employees","/pay-runs","/payslips","/deductions"],["sendgrid"],"auth,payroll,tax".split(",")),
    _ex(6,"fintech","P2P lending marketplace where borrowers list requests and lenders fund portions",
        [_e("LoanRequest","id:int","borrower_id:fk_User.id","amount:decimal","purpose","term_months:int","interest_rate:decimal","status:enum:pending,funded,active,repaid,defaulted","credit_score:int"),
         _e("LoanFunding","id:int","loan_id:fk_LoanRequest.id","lender_id:fk_User.id","amount:decimal","funded_at:datetime"),
         _e("Repayment","id:int","loan_id:fk_LoanRequest.id","due_date:datetime","amount:decimal","paid_at:datetime","status:enum:pending,paid,late"),
         _e("LenderAccount","id:int","user_id:fk_User.id","balance:decimal","total_invested:decimal","total_earned:decimal")],
        ["/loan-requests","/fundings","/repayments","/lender/dashboard"],["stripe"],"auth,p2p_lending,repayments".split(",")),
    _ex(7,"fintech","Corporate expense management with approval workflows, receipt capture, and policy enforcement",
        [_e("Employee","id:int","user_id:fk_User.id","department","manager_id:fk_User.id","expense_limit:decimal"),
         _e("ExpenseReport","id:int","employee_id:fk_Employee.id","title","period_start:datetime","period_end:datetime","status:enum:draft,submitted,approved,rejected,paid","total:decimal"),
         _e("Expense","id:int","report_id:fk_ExpenseReport.id","date:datetime","category:enum:travel,meals,accommodation,equipment,other","amount:decimal","currency","receipt_url","merchant","notes"),
         _e("ApprovalStep","id:int","report_id:fk_ExpenseReport.id","approver_id:fk_User.id","status:enum:pending,approved,rejected","decided_at:datetime","comments")],
        ["/expense-reports","/expenses","/approvals","/policies"],["sendgrid"],"auth,expense_management,approvals".split(",")),
    _ex(8,"fintech","Insurance claims processing with document upload, adjuster assignment, and payment tracking",
        [_e("Policy","id:int","policy_no","holder_id:fk_User.id","type:enum:auto,home,health,life","premium:decimal","coverage_amount:decimal","start_date:datetime","end_date:datetime"),
         _e("Claim","id:int","policy_id:fk_Policy.id","filed_at:datetime","incident_date:datetime","description","amount_claimed:decimal","status:enum:filed,under_review,approved,denied","adjuster_id:fk_User.id"),
         _e("ClaimDocument","id:int","claim_id:fk_Claim.id","name","url","uploaded_at:datetime"),
         _e("Payment","id:int","claim_id:fk_Claim.id","amount:decimal","paid_at:datetime","method:enum:bank_transfer,check","reference")],
        ["/policies","/claims","/claims/{id}/documents","/payments"],["sendgrid"],"auth,claims,document_management".split(",")),
    _ex(9,"fintech","Revenue-based financing platform for SaaS companies with MRR-linked repayments",
        [_e("Company","id:int","name","website","arr:decimal","mrr:decimal","growth_rate:decimal","industry"),
         _e("FinancingOffer","id:int","company_id:fk_Company.id","amount:decimal","revenue_share_pct:decimal","cap_multiple:decimal","status:enum:offered,accepted,declined"),
         _e("Repayment","id:int","offer_id:fk_FinancingOffer.id","month:str","mrr:decimal","amount_owed:decimal","amount_paid:decimal","paid_at:datetime"),
         _e("BankConnection","id:int","company_id:fk_Company.id","provider","access_token","last_synced:datetime")],
        ["/companies","/offers","/repayments","/bank-connections"],["stripe"],"auth,financing,bank_sync".split(",")),
    _ex(10,"fintech","Treasury management for mid-market companies with cash pooling and FX hedging",
        [_e("BankAccount","id:int","entity_id:fk_Entity.id","bank","account_no","currency","balance:decimal","type:enum:operating,payroll,reserve"),
         _e("CashPosition","id:int","date:datetime","account_id:fk_BankAccount.id","opening:decimal","inflows:decimal","outflows:decimal","closing:decimal"),
         _e("FxHedge","id:int","from_currency","to_currency","notional:decimal","rate:decimal","maturity:datetime","type:enum:forward,option","status:enum:open,settled"),
         _e("CashForecast","id:int","entity_id:fk_Entity.id","horizon_days:int","scenarios:json","generated_at:datetime")],
        ["/bank-accounts","/cash-positions","/fx-hedges","/forecasts"],[],"auth,treasury,fx_management".split(",")),
    _ex(11,"fintech","Buy-now-pay-later platform with installment plans and merchant integration API",
        [_e("Merchant","id:int","name","api_key","webhook_url","settlement_account","fee_pct:decimal"),
         _e("LoanApplication","id:int","user_id:fk_User.id","merchant_id:fk_Merchant.id","order_amount:decimal","installments:int","status:enum:pending,approved,declined"),
         _e("InstallmentPlan","id:int","application_id:fk_LoanApplication.id","installment_no:int","due_date:datetime","amount:decimal","status:enum:pending,paid,late"),
         _e("MerchantSettlement","id:int","merchant_id:fk_Merchant.id","period_start:datetime","period_end:datetime","amount:decimal","paid_at:datetime")],
        ["/applications","/installments","/merchants","/settlements"],["stripe"],"auth,bnpl,merchant_api".split(",")),
    _ex(12,"fintech","Freelancer invoicing with multi-currency support, VAT calculation, and Stripe payouts",
        [_e("Client","id:int","user_id:fk_User.id","name","country","currency","vat_number"),
         _e("Project","id:int","client_id:fk_Client.id","name","hourly_rate:decimal","currency","status:enum:active,paused,complete"),
         _e("Invoice","id:int","project_id:fk_Project.id","number","subtotal:decimal","vat_rate:decimal","vat_amount:decimal","total:decimal","currency","status:enum:draft,sent,paid"),
         _e("Payout","id:int","user_id:fk_User.id","amount:decimal","currency","stripe_transfer_id","paid_at:datetime")],
        ["/clients","/projects","/invoices","/payouts"],["stripe"],"auth,multi_currency,vat".split(",")),
    _ex(13,"fintech","Stock portfolio tracker with dividend tracking, asset allocation, and rebalancing alerts",
        [_e("Portfolio","id:int","user_id:fk_User.id","name","currency","benchmark_index"),
         _e("Holding","id:int","portfolio_id:fk_Portfolio.id","ticker","shares:decimal","avg_cost:decimal","current_price:decimal"),
         _e("Dividend","id:int","holding_id:fk_Holding.id","ex_date:datetime","pay_date:datetime","amount_per_share:decimal","total_received:decimal"),
         _e("RebalanceTarget","id:int","portfolio_id:fk_Portfolio.id","ticker","target_pct:decimal")],
        ["/portfolios","/holdings","/dividends","/rebalance"],[],"auth,portfolio,dividends".split(",")),
    _ex(14,"fintech","Microfinance platform for rural borrowers with group lending and loan officer mobile app",
        [_e("LendingGroup","id:int","name","village","loan_officer_id:fk_User.id","member_count:int","status:enum:active,dissolved"),
         _e("Member","id:int","group_id:fk_LendingGroup.id","first_name","last_name","id_no","phone","savings_balance:decimal"),
         _e("GroupLoan","id:int","group_id:fk_LendingGroup.id","amount:decimal","interest_rate:decimal","term_weeks:int","disbursed_at:datetime","status:enum:pending,active,repaid"),
         _e("WeeklyRepayment","id:int","loan_id:fk_GroupLoan.id","week_no:int","due_date:datetime","amount:decimal","collected:decimal","collected_at:datetime")],
        ["/groups","/members","/loans","/repayments"],["twilio"],"auth,group_lending,mobile".split(",")),
    _ex(15,"fintech","Accounts payable automation with invoice OCR, 3-way matching, and ERP sync",
        [_e("Vendor","id:int","name","tax_id","payment_terms_days:int","bank_account","email","currency"),
         _e("PurchaseOrder","id:int","vendor_id:fk_Vendor.id","po_no","ordered_at:datetime","total:decimal","status:enum:open,partial,received"),
         _e("VendorInvoice","id:int","vendor_id:fk_Vendor.id","po_id:fk_PurchaseOrder.id","invoice_no","amount:decimal","due_date:datetime","status:enum:received,matched,approved,paid"),
         _e("Payment","id:int","invoice_id:fk_VendorInvoice.id","amount:decimal","paid_at:datetime","reference","method:enum:bank_transfer,check,ach")],
        ["/vendors","/purchase-orders","/vendor-invoices","/payments"],[],"auth,ap_automation,3way_match".split(",")),
]

# ── SAAS ───────────────────────────────────────────────────────────────────────

_saas = [
    _ex(1,"saas","Project management tool with tasks, sprints, Kanban boards, and time tracking",
        [_e("Project","id:int","org_id:fk_Org.id","name","slug","description","status:enum:active,archived"),
         _e("Task","id:int","project_id:fk_Project.id","title","assignee_id:fk_User.id","status:enum:todo,in_progress,review,done","priority:enum:low,medium,high,urgent","due_date:datetime","estimate_hours:decimal"),
         _e("Sprint","id:int","project_id:fk_Project.id","name","start_date:datetime","end_date:datetime","goal","status:enum:planning,active,completed"),
         _e("TimeEntry","id:int","task_id:fk_Task.id","user_id:fk_User.id","hours:decimal","date:datetime","notes")],
        ["/projects","/tasks","/sprints","/time-entries"],[],"auth,multi_tenant,kanban,sprints".split(",")),
    _ex(2,"saas","CRM for sales teams with pipeline stages, deal tracking, and activity logging",
        [_e("Contact","id:int","org_id:fk_Org.id","first_name","last_name","email","phone","company","title"),
         _e("Deal","id:int","contact_id:fk_Contact.id","title","value:decimal","stage:enum:lead,qualified,proposal,negotiation,closed_won,closed_lost","close_date:datetime","owner_id:fk_User.id"),
         _e("Activity","id:int","deal_id:fk_Deal.id","user_id:fk_User.id","type:enum:call,email,meeting,note","notes","occurred_at:datetime"),
         _e("Pipeline","id:int","org_id:fk_Org.id","name","stages:json")],
        ["/contacts","/deals","/activities","/pipeline"],[],"auth,multi_tenant,crm,pipeline".split(",")),
    _ex(3,"saas","Customer help desk with ticket routing, SLA tracking, and canned responses",
        [_e("Ticket","id:int","org_id:fk_Org.id","subject","body","status:enum:open,pending,resolved,closed","priority:enum:low,normal,high","assignee_id:fk_User.id","customer_email","created_at:datetime"),
         _e("TicketMessage","id:int","ticket_id:fk_Ticket.id","author_id:fk_User.id","body","is_internal:bool","created_at:datetime"),
         _e("SlaPolicy","id:int","org_id:fk_Org.id","name","first_response_hours:int","resolution_hours:int","priority:enum:low,normal,high"),
         _e("CannedResponse","id:int","org_id:fk_Org.id","name","body","category")],
        ["/tickets","/tickets/{id}/messages","/sla-policies","/canned-responses"],["sendgrid"],"auth,multi_tenant,helpdesk,sla".split(",")),
    _ex(4,"saas","HR management system with org chart, leave management, and performance reviews",
        [_e("Employee","id:int","org_id:fk_Org.id","user_id:fk_User.id","first_name","last_name","department","job_title","manager_id:fk_Employee.id","start_date:datetime","status:enum:active,on_leave,terminated"),
         _e("LeaveRequest","id:int","employee_id:fk_Employee.id","type:enum:annual,sick,maternity,paternity","start_date:datetime","end_date:datetime","days:int","status:enum:pending,approved,rejected","approver_id:fk_User.id"),
         _e("PerformanceReview","id:int","employee_id:fk_Employee.id","reviewer_id:fk_User.id","period","ratings:json","comments","overall_score:decimal","completed_at:datetime"),
         _e("Department","id:int","org_id:fk_Org.id","name","head_id:fk_Employee.id","parent_id:fk_Department.id")],
        ["/employees","/leave-requests","/performance-reviews","/departments"],["sendgrid"],"auth,multi_tenant,hr,leave_management".split(",")),
    _ex(5,"saas","Learning management system with courses, quizzes, certificates, and progress tracking",
        [_e("Course","id:int","title","slug","description","instructor_id:fk_User.id","status:enum:draft,published","price:decimal","duration_hours:decimal"),
         _e("Lesson","id:int","course_id:fk_Course.id","title","order_index:int","content_type:enum:video,text,quiz","content_url","duration_min:int"),
         _e("Enrollment","id:int","user_id:fk_User.id","course_id:fk_Course.id","enrolled_at:datetime","completed_at:datetime","progress_pct:decimal"),
         _e("QuizAttempt","id:int","lesson_id:fk_Lesson.id","user_id:fk_User.id","answers:json","score:decimal","passed:bool","attempted_at:datetime"),
         _e("Certificate","id:int","enrollment_id:fk_Enrollment.id","issued_at:datetime","url")],
        ["/courses","/lessons","/enrollments","/certificates"],["stripe"],"auth,lms,quizzes,certificates".split(",")),
    _ex(6,"saas","OKR tracker with company/team/individual objectives and weekly check-ins",
        [_e("Objective","id:int","org_id:fk_Org.id","title","owner_id:fk_User.id","period","level:enum:company,team,individual","status:enum:on_track,at_risk,behind","parent_id:fk_Objective.id"),
         _e("KeyResult","id:int","objective_id:fk_Objective.id","title","type:enum:percentage,number,currency,milestone","start_value:decimal","target_value:decimal","current_value:decimal"),
         _e("CheckIn","id:int","key_result_id:fk_KeyResult.id","user_id:fk_User.id","value:decimal","confidence:int","notes","checked_at:datetime")],
        ["/objectives","/key-results","/check-ins","/reports"],[],"auth,multi_tenant,okr,reporting".split(",")),
    _ex(7,"saas","Customer success platform with health scores, playbooks, and renewal tracking",
        [_e("Account","id:int","name","arr:decimal","tier:enum:starter,growth,enterprise","csm_id:fk_User.id","renewal_date:datetime","health_score:int"),
         _e("HealthFactor","id:int","account_id:fk_Account.id","factor:enum:product_usage,support_tickets,nps,payment_history","score:int","recorded_at:datetime"),
         _e("Playbook","id:int","name","trigger:enum:low_health,upcoming_renewal,onboarding","tasks:json"),
         _e("PlaybookRun","id:int","account_id:fk_Account.id","playbook_id:fk_Playbook.id","started_at:datetime","status:enum:active,completed","completed_tasks:json")],
        ["/accounts","/health-scores","/playbooks","/playbook-runs"],["sendgrid"],"auth,customer_success,playbooks".split(",")),
    _ex(8,"saas","API management portal with key provisioning, rate limiting, and usage analytics",
        [_e("ApiProduct","id:int","name","slug","description","base_url","status:enum:active,deprecated"),
         _e("ApiKey","id:int","user_id:fk_User.id","product_id:fk_ApiProduct.id","key_prefix","key_hash","name","rate_limit:int","monthly_quota:int","last_used:datetime","status:enum:active,revoked"),
         _e("ApiUsage","id:int","key_id:fk_ApiKey.id","endpoint","method","status_code:int","response_ms:int","recorded_at:datetime"),
         _e("Plan","id:int","name","rate_limit_per_min:int","monthly_quota:int","price:decimal")],
        ["/api-products","/api-keys","/usage","/plans"],["stripe"],"auth,api_management,rate_limiting".split(",")),
    _ex(9,"saas","Survey and feedback platform with logic branching, NPS tracking, and report export",
        [_e("Survey","id:int","org_id:fk_Org.id","title","description","status:enum:draft,active,closed","created_by:fk_User.id"),
         _e("Question","id:int","survey_id:fk_Survey.id","type:enum:nps,rating,multiple_choice,text,matrix","text","options:json","required:bool","order_index:int"),
         _e("Response","id:int","survey_id:fk_Survey.id","respondent_email","answers:json","submitted_at:datetime","ip_address"),
         _e("SurveyDistribution","id:int","survey_id:fk_Survey.id","method:enum:email,link,embed","sent_count:int","open_count:int","complete_count:int")],
        ["/surveys","/questions","/responses","/reports"],["sendgrid"],"auth,multi_tenant,surveys,nps".split(",")),
    _ex(10,"saas","Revenue intelligence platform with deal forecasting, pipeline analytics, and quota tracking",
        [_e("SalesRep","id:int","user_id:fk_User.id","quota:decimal","team_id:fk_Team.id","region"),
         _e("Deal","id:int","rep_id:fk_SalesRep.id","name","value:decimal","close_date:datetime","stage","probability:int","forecast_category:enum:pipeline,best_case,commit,closed"),
         _e("ForecastSubmission","id:int","rep_id:fk_SalesRep.id","period","commit_amount:decimal","best_case:decimal","submitted_at:datetime"),
         _e("QuotaAttainment","id:int","rep_id:fk_SalesRep.id","period","quota:decimal","achieved:decimal")],
        ["/deals","/forecasts","/quotas","/reports/pipeline"],[],"auth,forecasting,quota_tracking".split(",")),
    _ex(11,"saas","Knowledge base and documentation platform with versioning and public/private spaces",
        [_e("Space","id:int","org_id:fk_Org.id","name","slug","is_public:bool"),
         _e("Article","id:int","space_id:fk_Space.id","title","slug","body","author_id:fk_User.id","status:enum:draft,published","version:int","parent_id:fk_Article.id"),
         _e("ArticleVersion","id:int","article_id:fk_Article.id","body","version:int","saved_by:fk_User.id","created_at:datetime"),
         _e("Feedback","id:int","article_id:fk_Article.id","helpful:bool","comment","created_at:datetime")],
        ["/spaces","/articles","/articles/{id}/versions","/search"],[],"auth,multi_tenant,docs,versioning".split(",")),
    _ex(12,"saas","Subscription billing platform with usage metering, invoicing, and dunning",
        [_e("Plan","id:int","name","interval:enum:monthly,annual","base_price:decimal","features:json"),
         _e("Subscription","id:int","org_id:fk_Org.id","plan_id:fk_Plan.id","status:enum:trialing,active,past_due,cancelled","trial_ends:datetime","current_period_end:datetime"),
         _e("UsageMeter","id:int","subscription_id:fk_Subscription.id","metric","quantity:decimal","period:str"),
         _e("BillingInvoice","id:int","subscription_id:fk_Subscription.id","amount:decimal","status:enum:draft,open,paid,void","due_date:datetime","stripe_invoice_id")],
        ["/plans","/subscriptions","/usage","/invoices"],["stripe"],"auth,billing,usage_metering,dunning".split(",")),
    _ex(13,"saas","Product feedback and roadmap tool with voting, status updates, and changelog",
        [_e("Board","id:int","org_id:fk_Org.id","name","is_public:bool"),
         _e("FeatureRequest","id:int","board_id:fk_Board.id","title","description","status:enum:under_review,planned,in_progress,complete","vote_count:int","author_id:fk_User.id"),
         _e("Vote","id:int","feature_id:fk_FeatureRequest.id","user_id:fk_User.id","voted_at:datetime"),
         _e("ChangelogEntry","id:int","org_id:fk_Org.id","title","body","version","published_at:datetime","linked_features:json")],
        ["/boards","/features","/votes","/changelog"],["sendgrid"],"auth,multi_tenant,roadmap,voting".split(",")),
    _ex(14,"saas","Affiliate management platform with link tracking, commission calculation, and payouts",
        [_e("Affiliate","id:int","user_id:fk_User.id","code","commission_pct:decimal","status:enum:pending,active,suspended","balance:decimal"),
         _e("AffiliateLink","id:int","affiliate_id:fk_Affiliate.id","url","slug","clicks:int","conversions:int"),
         _e("Conversion","id:int","link_id:fk_AffiliateLink.id","order_id","order_value:decimal","commission:decimal","status:enum:pending,approved,paid","converted_at:datetime"),
         _e("Payout","id:int","affiliate_id:fk_Affiliate.id","amount:decimal","method:enum:paypal,bank_transfer","status:enum:pending,paid","paid_at:datetime")],
        ["/affiliates","/links","/conversions","/payouts"],["stripe"],"auth,affiliate_tracking,commissions".split(",")),
    _ex(15,"saas","Time tracking and billing for professional services firms with project budgets",
        [_e("Client","id:int","org_id:fk_Org.id","name","email","billing_rate:decimal","currency"),
         _e("Project","id:int","client_id:fk_Client.id","name","budget_hours:decimal","budget_amount:decimal","status:enum:active,on_hold,complete"),
         _e("TimeEntry","id:int","project_id:fk_Project.id","user_id:fk_User.id","date:datetime","hours:decimal","description","billable:bool","billed:bool"),
         _e("Invoice","id:int","client_id:fk_Client.id","period_start:datetime","period_end:datetime","hours:decimal","amount:decimal","status:enum:draft,sent,paid")],
        ["/clients","/projects","/time-entries","/invoices"],["stripe"],"auth,multi_tenant,time_billing".split(",")),
]

# ── AI_INTEGRATED (abbreviated — 12 examples) ──────────────────────────────────

_ai_integrated = [
    _ex(1,"ai_integrated","AI writing assistant with document editor, tone controls, and team sharing",
        [_e("Document","id:int","user_id:fk_User.id","title","content","word_count:int","status:enum:draft,published"),
         _e("GenerationRequest","id:int","document_id:fk_Document.id","prompt","tone:enum:professional,casual,persuasive,academic","model","output","tokens_used:int","created_at:datetime"),
         _e("Collaboration","id:int","document_id:fk_Document.id","user_id:fk_User.id","role:enum:editor,viewer")],
        ["/documents","/generate","/documents/{id}/share"],[],"auth,llm,collaboration".split(",")),
    _ex(2,"ai_integrated","Chatbot builder platform with intent training, entity extraction, and analytics",
        [_e("Bot","id:int","org_id:fk_Org.id","name","slug","model","system_prompt","status:enum:draft,testing,live"),
         _e("Intent","id:int","bot_id:fk_Bot.id","name","examples:json","response_template"),
         _e("Conversation","id:int","bot_id:fk_Bot.id","session_id","messages:json","started_at:datetime","user_feedback:int"),
         _e("BotAnalytics","id:int","bot_id:fk_Bot.id","date:datetime","total_conversations:int","avg_turns:decimal","resolution_rate:decimal")],
        ["/bots","/bots/{id}/chat","/intents","/analytics"],[],"auth,multi_tenant,chatbot,analytics".split(",")),
    _ex(3,"ai_integrated","Document analysis platform for contracts with clause extraction and risk scoring",
        [_e("Document","id:int","org_id:fk_Org.id","name","type:enum:contract,nda,sow,msa","file_url","status:enum:uploaded,processing,analyzed"),
         _e("Clause","id:int","document_id:fk_Document.id","type","text","page:int","risk_level:enum:low,medium,high","notes"),
         _e("AnalysisReport","id:int","document_id:fk_Document.id","overall_risk:enum:low,medium,high","summary","recommendations:json","created_at:datetime")],
        ["/documents","/documents/{id}/analyze","/documents/{id}/clauses","/reports"],[],"auth,document_analysis,risk".split(",")),
    _ex(4,"ai_integrated","AI code review tool that checks PRs for security issues and style violations",
        [_e("Repository","id:int","org_id:fk_Org.id","name","provider:enum:github,gitlab,bitbucket","webhook_secret"),
         _e("PullRequest","id:int","repo_id:fk_Repository.id","pr_number:int","title","author","status:enum:open,merged,closed"),
         _e("ReviewComment","id:int","pr_id:fk_PullRequest.id","file_path","line_no:int","severity:enum:info,warning,error","category:enum:security,style,performance,logic","body"),
         _e("ReviewSummary","id:int","pr_id:fk_PullRequest.id","security_score:int","style_score:int","overall","created_at:datetime")],
        ["/repositories","/pull-requests","/pull-requests/{id}/review","/comments"],[],"auth,code_review,webhooks".split(",")),
    _ex(5,"ai_integrated","Meeting summarizer with transcription, action item extraction, and calendar sync",
        [_e("Meeting","id:int","user_id:fk_User.id","title","date:datetime","duration_min:int","platform:enum:zoom,teams,google_meet","status:enum:scheduled,processing,complete"),
         _e("Transcript","id:int","meeting_id:fk_Meeting.id","content","speakers:json","word_count:int"),
         _e("Summary","id:int","meeting_id:fk_Meeting.id","key_points:json","decisions:json","action_items:json","generated_at:datetime"),
         _e("ActionItem","id:int","summary_id:fk_Summary.id","description","assignee","due_date:datetime","status:enum:open,done")],
        ["/meetings","/meetings/{id}/transcript","/meetings/{id}/summary","/action-items"],["sendgrid"],"auth,transcription,summarization".split(",")),
    _ex(6,"ai_integrated","ML model registry with experiment tracking, versioning, and deployment management",
        [_e("Experiment","id:int","org_id:fk_Org.id","name","description","created_by:fk_User.id","status:enum:running,completed,failed"),
         _e("Run","id:int","experiment_id:fk_Experiment.id","parameters:json","metrics:json","artifacts:json","started_at:datetime","ended_at:datetime","status:enum:running,success,failed"),
         _e("ModelVersion","id:int","experiment_id:fk_Experiment.id","run_id:fk_Run.id","version:int","artifact_url","framework","stage:enum:staging,production,archived"),
         _e("Deployment","id:int","model_id:fk_ModelVersion.id","endpoint_url","status:enum:deploying,active,stopped","requests_per_day:int")],
        ["/experiments","/runs","/models","/deployments"],[],"auth,experiment_tracking,model_registry".split(",")),
    _ex(7,"ai_integrated","AI-powered resume screener with job matching, scoring, and ATS integration",
        [_e("Job","id:int","org_id:fk_Org.id","title","description","requirements:json","status:enum:draft,open,closed"),
         _e("Application","id:int","job_id:fk_Job.id","candidate_name","email","resume_url","status:enum:new,screened,interview,offer,rejected"),
         _e("ScreeningResult","id:int","application_id:fk_Application.id","match_score:int","strengths:json","gaps:json","recommendation:enum:strong_yes,yes,maybe,no","created_at:datetime"),
         _e("Interview","id:int","application_id:fk_Application.id","type:enum:phone,video,technical","scheduled_at:datetime","interviewer_id:fk_User.id","notes","feedback")],
        ["/jobs","/applications","/applications/{id}/screen","/interviews"],["sendgrid"],"auth,ai_screening,ats".split(",")),
    _ex(8,"ai_integrated","Translation management platform with AI translation, human review, and glossary enforcement",
        [_e("Project","id:int","org_id:fk_Org.id","name","source_lang","target_langs:json","domain:enum:marketing,legal,technical,medical"),
         _e("StringKey","id:int","project_id:fk_Project.id","key","source_text","context","character_limit:int"),
         _e("Translation","id:int","string_id:fk_StringKey.id","language","text","method:enum:ai,human","status:enum:draft,review,approved","translator_id:fk_User.id"),
         _e("GlossaryTerm","id:int","project_id:fk_Project.id","source_term","target_term","language","notes")],
        ["/projects","/strings","/translations","/glossary"],[],"auth,multi_tenant,translation,localization".split(",")),
    _ex(9,"ai_integrated","Sentiment analysis dashboard for brand monitoring with social media ingestion",
        [_e("Brand","id:int","org_id:fk_Org.id","name","keywords:json","channels:json"),
         _e("Mention","id:int","brand_id:fk_Brand.id","source:enum:twitter,reddit,news,review_site","text","author","url","published_at:datetime"),
         _e("SentimentResult","id:int","mention_id:fk_Mention.id","sentiment:enum:positive,neutral,negative","score:decimal","topics:json","analyzed_at:datetime"),
         _e("SentimentTrend","id:int","brand_id:fk_Brand.id","date:datetime","positive_pct:decimal","neutral_pct:decimal","negative_pct:decimal","mention_count:int")],
        ["/brands","/mentions","/sentiment","/trends"],[],"auth,sentiment,social_listening".split(",")),
    _ex(10,"ai_integrated","AI email assistant that drafts replies, categorizes inbox, and schedules follow-ups",
        [_e("EmailAccount","id:int","user_id:fk_User.id","email","provider:enum:gmail,outlook","access_token","refresh_token"),
         _e("Email","id:int","account_id:fk_EmailAccount.id","message_id","subject","from_address","body","received_at:datetime","category:enum:important,promotional,social,update,other"),
         _e("DraftReply","id:int","email_id:fk_Email.id","body","tone:enum:professional,friendly,brief","created_at:datetime","accepted:bool"),
         _e("FollowUpReminder","id:int","email_id:fk_Email.id","remind_at:datetime","status:enum:pending,sent","notes")],
        ["/accounts","/emails","/emails/{id}/draft-reply","/follow-ups"],["sendgrid"],"auth,email_ai,follow_ups".split(",")),
    _ex(11,"ai_integrated","AI pricing optimizer for e-commerce with competitor monitoring and demand forecasting",
        [_e("Product","id:int","org_id:fk_Org.id","sku","name","current_price:decimal","cost:decimal","category"),
         _e("CompetitorPrice","id:int","product_id:fk_Product.id","competitor_url","price:decimal","in_stock:bool","captured_at:datetime"),
         _e("PriceRecommendation","id:int","product_id:fk_Product.id","recommended_price:decimal","confidence:decimal","reason","created_at:datetime","applied:bool"),
         _e("DemandForecast","id:int","product_id:fk_Product.id","forecast_date:datetime","predicted_units:int","confidence_interval:json")],
        ["/products","/competitor-prices","/recommendations","/forecasts"],[],"auth,pricing,demand_forecasting".split(",")),
    _ex(12,"ai_integrated","AI data labeling platform with annotation tools, quality control, and model export",
        [_e("Dataset","id:int","org_id:fk_Org.id","name","type:enum:image,text,audio,video","status:enum:importing,labeling,complete"),
         _e("DataItem","id:int","dataset_id:fk_Dataset.id","file_url","metadata:json","status:enum:pending,in_progress,complete"),
         _e("Annotation","id:int","item_id:fk_DataItem.id","labeler_id:fk_User.id","labels:json","confidence:decimal","time_spent_sec:int"),
         _e("QualityCheck","id:int","annotation_id:fk_Annotation.id","reviewer_id:fk_User.id","approved:bool","feedback")],
        ["/datasets","/items","/annotations","/export"],[],"auth,labeling,quality_control".split(",")),
]

# ── Compact remaining domains (10 each) ───────────────────────────────────────

def _quick(domain, items):
    """Build compact examples from (description, entity_names_csv) tuples."""
    result = []
    for i, (desc, ents_str) in enumerate(items, 1):
        ents = [_e(n, "id:int","name","status:enum:active,inactive","created_at:datetime") for n in ents_str.split(",")]
        result.append(_ex(i, domain, desc, ents, [f"/{e['name'].lower()}s" for e in ents[:3]], [], ["auth","crud"]))
    return result


_marketplace = _quick("marketplace", [
    ("Freelancer marketplace with project bidding, escrow, and milestone payments", "Project,Bid,Contract,Milestone"),
    ("Job board for tech companies with applicant tracking and interview scheduling", "JobPosting,Application,Interview,Offer"),
    ("Real estate listings with agent profiles, virtual tours, and mortgage calculator", "Listing,Agent,ViewingRequest,SavedListing"),
    ("Used car marketplace with inspection reports, price history, and financing", "CarListing,InspectionReport,Offer,FinancingRequest"),
    ("Food delivery platform with restaurant menus, order tracking, and driver app", "Restaurant,MenuItem,Order,Delivery"),
    ("Online tutoring marketplace with lesson booking, video sessions, and reviews", "Tutor,Lesson,Booking,Review"),
    ("Home services booking for cleaners, plumbers, and electricians", "ServiceProvider,Service,Booking,Review"),
    ("Event ticket marketplace with seat selection and transfer support", "Event,Ticket,Order,Transfer"),
    ("Vacation rental platform with availability calendar and host messaging", "Property,Booking,Review,Message"),
    ("B2B wholesale procurement with RFQ, bulk pricing, and supplier ratings", "Supplier,RfqRequest,Quote,PurchaseOrder"),
])

_erp = _quick("erp", [
    ("Inventory management with multi-warehouse, FIFO costing, and reorder alerts", "Item,Warehouse,StockLevel,PurchaseOrder"),
    ("Manufacturing orders with BOM, work centers, and production scheduling", "Product,BillOfMaterial,WorkOrder,WorkCenter"),
    ("Procurement system with vendor management, approval workflows, and 3-way matching", "Vendor,PurchaseOrder,GoodsReceipt,VendorInvoice"),
    ("Warehouse management with pick/pack/ship, barcode scanning, and location tracking", "Location,StockMove,PickingOrder,ShipmentLabel"),
    ("Quality control with inspection plans, non-conformance reports, and corrective actions", "InspectionPlan,InspectionResult,NonConformance,CorrectiveAction"),
    ("Fixed asset management with depreciation schedules and disposal tracking", "Asset,DepreciationSchedule,MaintenanceRecord,Disposal"),
    ("Fleet management with vehicle tracking, fuel logs, and maintenance scheduling", "Vehicle,FuelLog,MaintenanceJob,DriverAssignment"),
    ("Production planning with demand forecasting, MRP, and capacity planning", "ProductionPlan,MaterialRequirement,CapacityLoad,WorkOrder"),
    ("Supply chain visibility with multi-tier supplier tracking and risk scoring", "Supplier,SupplierTier,RiskScore,ShipmentTracking"),
    ("Maintenance management (CMMS) with preventive schedules and spare parts", "Equipment,MaintenanceSchedule,WorkOrder,SparePart"),
])

_government = _quick("government", [
    ("Building permit management with plan review, inspections, and certificate issuance", "PermitApplication,PlanReview,Inspection,Certificate"),
    ("Citizen services portal for utility billing, tax payments, and service requests", "Citizen,ServiceRequest,Invoice,Payment"),
    ("Grant management for disbursement tracking, milestone reporting, and audits", "GrantProgram,Application,Award,MilestoneReport"),
    ("License renewal portal for business, professional, and vehicle licenses", "LicenseType,LicenseHolder,RenewalApplication,Payment"),
    ("Public procurement with RFP publishing, bid submission, and award management", "Rfp,Bid,EvaluationScore,Contract"),
    ("Court case management with hearing scheduling, document filing, and judgments", "Case,Party,Hearing,Document"),
    ("Land registry with parcel records, ownership transfers, and encumbrances", "Parcel,Owner,Transfer,Encumbrance"),
    ("Social services case management for benefits, referrals, and outcomes tracking", "Client,CaseWorker,ServicePlan,Outcome"),
    ("Public health reporting with disease surveillance and outbreak tracking", "Disease,Report,Outbreak,ResponseAction"),
    ("Voter registration with address verification, polling place assignment, and audit", "Voter,PollingPlace,Registration,AuditLog"),
])

_traditional_erp = _quick("traditional_erp", [
    ("General ledger with chart of accounts, journal entries, and period close", "Account,JournalEntry,JournalLine,FiscalPeriod"),
    ("Accounts payable with vendor invoices, payment runs, and aging reports", "Vendor,VendorInvoice,PaymentRun,PaymentLine"),
    ("Accounts receivable with customer invoices, collections, and aging", "Customer,CustomerInvoice,Receipt,CollectionAction"),
    ("Payroll with salary grades, deductions, tax filing, and bank transfer", "Employee,PayRun,PaySlip,TaxFiling"),
    ("Fixed assets with depreciation, revaluations, and disposal accounting", "Asset,DepreciationRun,Revaluation,Disposal"),
    ("Project accounting with budgets, timesheets, and cost allocation", "Project,Budget,Timesheet,CostAllocation"),
    ("Bank reconciliation with statement import and matching rules", "BankStatement,BankLine,ReconciliationRule,MatchedEntry"),
    ("Budget planning with scenario modeling, approval, and variance tracking", "Budget,BudgetLine,Scenario,Variance"),
    ("Financial consolidation with intercompany eliminations and minority interest", "Entity,ConsolidationRun,IntercompanyElim,ConsolidatedReport"),
    ("Management reporting with KPI dashboards, drill-down, and scheduled delivery", "KpiMetric,Report,ReportSchedule,Dashboard"),
])

# ── SQLALCHEMY MODEL EXAMPLES ──────────────────────────────────────────────────

_sqla = {
    "domain": "cross_domain", "version": "1.0", "generated_at": NOW,
    "examples": [
        {"id": "sqla_001", "type": "entity_to_sqlalchemy", "domain": "ecommerce", "tags": ["model", "enum", "decimal"],
         "input": {"name": "Product", "fields": [{"name": "id", "type": "int"}, {"name": "price", "type": "decimal"}, {"name": "status", "type": "enum", "values": ["active","inactive"]}]},
         "output": "class Product(Base):\n    __tablename__ = 'products'\n    id = Column(Integer, primary_key=True, index=True)\n    name = Column(String(255), nullable=False)\n    price = Column(Numeric(10, 2), nullable=False)\n    status = Column(Enum('active', 'inactive', name='product_status'), default='active')\n    created_at = Column(DateTime(timezone=True), server_default=func.now())"},
        {"id": "sqla_002", "type": "entity_to_sqlalchemy", "domain": "saas", "tags": ["model", "fk", "relationship"],
         "input": {"name": "Comment", "fields": [{"name": "id", "type": "int"}, {"name": "post_id", "type": "int", "foreign_key": "Post.id"}, {"name": "user_id", "type": "int", "foreign_key": "User.id"}, {"name": "body", "type": "str"}]},
         "output": "class Comment(Base):\n    __tablename__ = 'comments'\n    id = Column(Integer, primary_key=True, index=True)\n    post_id = Column(Integer, ForeignKey('posts.id', ondelete='CASCADE'), nullable=False, index=True)\n    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)\n    body = Column(Text, nullable=False)\n    created_at = Column(DateTime(timezone=True), server_default=func.now())\n    post = relationship('Post', back_populates='comments')\n    user = relationship('User')"},
        {"id": "sqla_003", "type": "entity_to_sqlalchemy", "domain": "saas", "tags": ["model", "json", "unique"],
         "input": {"name": "ApiKey", "fields": [{"name": "id", "type": "int"}, {"name": "key_hash", "type": "str", "unique": True}, {"name": "scopes", "type": "json"}]},
         "output": "class ApiKey(Base):\n    __tablename__ = 'api_keys'\n    id = Column(Integer, primary_key=True, index=True)\n    name = Column(String(100), nullable=False)\n    key_hash = Column(String(64), unique=True, nullable=False, index=True)\n    scopes = Column(JSON, default=list)\n    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)\n    last_used = Column(DateTime(timezone=True), nullable=True)\n    revoked_at = Column(DateTime(timezone=True), nullable=True)\n    created_at = Column(DateTime(timezone=True), server_default=func.now())"},
        {"id": "sqla_004", "type": "entity_to_sqlalchemy", "domain": "saas", "tags": ["model", "uuid", "pk"],
         "input": {"name": "Session", "fields": [{"name": "id", "type": "uuid"}, {"name": "user_id", "type": "int"}, {"name": "expires_at", "type": "datetime"}]},
         "output": "import uuid\nclass Session(Base):\n    __tablename__ = 'sessions'\n    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))\n    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)\n    token_hash = Column(String(64), unique=True, nullable=False)\n    expires_at = Column(DateTime(timezone=True), nullable=False)\n    created_at = Column(DateTime(timezone=True), server_default=func.now())\n    user = relationship('User')"},
        {"id": "sqla_005", "type": "entity_to_sqlalchemy", "domain": "ecommerce", "tags": ["model", "many_to_many", "association"],
         "input": {"name": "ProductTag", "note": "Association table for many-to-many between Product and Tag"},
         "output": "product_tags = Table(\n    'product_tags', Base.metadata,\n    Column('product_id', Integer, ForeignKey('products.id', ondelete='CASCADE'), primary_key=True),\n    Column('tag_id', Integer, ForeignKey('tags.id', ondelete='CASCADE'), primary_key=True),\n)\n\n# In Product model:\n# tags = relationship('Tag', secondary=product_tags, back_populates='products')"},
        {"id": "sqla_006", "type": "entity_to_sqlalchemy", "domain": "ecommerce", "tags": ["model", "soft_delete"],
         "input": {"name": "Order", "fields": [{"name": "id", "type": "int"}, {"name": "deleted_at", "type": "datetime", "nullable": True}]},
         "output": "class Order(Base):\n    __tablename__ = 'orders'\n    id = Column(Integer, primary_key=True, index=True)\n    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)\n    total = Column(Numeric(10, 2), nullable=False)\n    status = Column(Enum('pending','paid','shipped','delivered','cancelled', name='order_status'), default='pending')\n    deleted_at = Column(DateTime(timezone=True), nullable=True)\n    created_at = Column(DateTime(timezone=True), server_default=func.now())\n\n    @property\n    def is_deleted(self):\n        return self.deleted_at is not None"},
        {"id": "sqla_007", "type": "entity_to_sqlalchemy", "domain": "saas", "tags": ["model", "composite_unique", "index"],
         "input": {"name": "OrgMember", "fields": [{"name": "org_id", "type": "int"}, {"name": "user_id", "type": "int"}, {"name": "role", "type": "enum"}]},
         "output": "class OrgMember(Base):\n    __tablename__ = 'org_members'\n    __table_args__ = (UniqueConstraint('org_id', 'user_id', name='uq_org_member'),)\n    id = Column(Integer, primary_key=True, index=True)\n    org_id = Column(Integer, ForeignKey('orgs.id', ondelete='CASCADE'), nullable=False, index=True)\n    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)\n    role = Column(Enum('owner','admin','member', name='member_role'), default='member')\n    joined_at = Column(DateTime(timezone=True), server_default=func.now())"},
        {"id": "sqla_008", "type": "entity_to_sqlalchemy", "domain": "healthcare", "tags": ["model", "check_constraint"],
         "input": {"name": "VitalSign", "fields": [{"name": "pulse", "type": "int"}, {"name": "bp_systolic", "type": "int"}]},
         "output": "class VitalSign(Base):\n    __tablename__ = 'vital_signs'\n    __table_args__ = (\n        CheckConstraint('pulse > 0 AND pulse < 300', name='ck_pulse_range'),\n        CheckConstraint('bp_systolic > 50 AND bp_systolic < 300', name='ck_bp_range'),\n    )\n    id = Column(Integer, primary_key=True, index=True)\n    patient_id = Column(Integer, ForeignKey('patients.id'), nullable=False, index=True)\n    pulse = Column(Integer, nullable=True)\n    bp_systolic = Column(Integer, nullable=True)\n    bp_diastolic = Column(Integer, nullable=True)\n    temp_c = Column(Numeric(4, 1), nullable=True)\n    recorded_at = Column(DateTime(timezone=True), server_default=func.now())"},
        {"id": "sqla_009", "type": "entity_to_sqlalchemy", "domain": "saas", "tags": ["model", "audit_fields"],
         "input": {"name": "AuditedModel", "note": "Mixin for models needing created_by / updated_by audit fields"},
         "output": "class AuditMixin:\n    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)\n    updated_by = Column(Integer, ForeignKey('users.id'), nullable=True)\n    created_at = Column(DateTime(timezone=True), server_default=func.now())\n    updated_at = Column(DateTime(timezone=True), onupdate=func.now())\n\nclass Document(AuditMixin, Base):\n    __tablename__ = 'documents'\n    id = Column(Integer, primary_key=True)\n    title = Column(String(255), nullable=False)\n    body = Column(Text)"},
        {"id": "sqla_010", "type": "entity_to_sqlalchemy", "domain": "ecommerce", "tags": ["model", "self_referential"],
         "input": {"name": "Category", "fields": [{"name": "parent_id", "type": "int", "foreign_key": "Category.id", "nullable": True}]},
         "output": "class Category(Base):\n    __tablename__ = 'categories'\n    id = Column(Integer, primary_key=True, index=True)\n    name = Column(String(100), nullable=False)\n    slug = Column(String(100), unique=True, nullable=False)\n    parent_id = Column(Integer, ForeignKey('categories.id'), nullable=True, index=True)\n    children = relationship('Category', back_populates='parent', lazy='dynamic')\n    parent = relationship('Category', back_populates='children', remote_side=[id])"},
    ]
}

# ── BUG FIX EXAMPLES ──────────────────────────────────────────────────────────

def _bug(idx, bug_class, error, file_, bad, fix, explanation, tags=None):
    return {"id": f"bug_{idx:03d}", "type": "bug_to_fix", "input": {"error": error, "file": file_, "bad_code": bad},
            "output": {"fix": fix, "explanation": explanation, "bug_class": bug_class},
            "tags": tags or [bug_class.lower(), "fastapi"]}


_bug_examples = [
    # RELATIVE_IMPORT (15)
    _bug(1,"RELATIVE_IMPORT","ImportError: attempted relative import with no known parent package","routers/crud.py","from .models import User, Product","from src.models import User, Product","App runs with PYTHONPATH=/app. src is a top-level package, not a sub-package."),
    _bug(2,"RELATIVE_IMPORT","ImportError: attempted relative import","routers/crud.py","from .schemas import UserCreate, UserOut","from src.schemas import UserCreate, UserOut","Use absolute imports everywhere. src/ is on PYTHONPATH."),
    _bug(3,"RELATIVE_IMPORT","ImportError","main.py","from .database import get_db, engine","from src.database import get_db, engine","main.py is loaded directly by uvicorn, relative imports have no parent."),
    _bug(4,"RELATIVE_IMPORT","ImportError: attempted relative import","services.py","from ..models import Order\nfrom ..database import get_db","from src.models import Order\nfrom src.database import get_db","Never use .. — use absolute path from src root."),
    _bug(5,"RELATIVE_IMPORT","ImportError","routers/crud.py","from . import schemas","from src import schemas","Relative dot-import of a module — use absolute."),
    _bug(6,"RELATIVE_IMPORT","ImportError: no known parent package","routers/crud.py","from..models import Product","from src.models import Product","Bedrock Nova variant: no space after from. Same fix."),
    _bug(7,"RELATIVE_IMPORT","ModuleNotFoundError","routers/auth.py","from .models import User\nfrom .utils import hash_password","from src.models import User\nfrom src.utils import hash_password","Auth router uses relative imports. Fix all to absolute."),
    _bug(8,"RELATIVE_IMPORT","ImportError","seed.py","from .models import Base, User, Product","from src.models import Base, User, Product","Seed script must use absolute imports when run standalone."),
    _bug(9,"RELATIVE_IMPORT","ImportError","routers/crud.py","from .schemas import (ItemCreate, ItemUpdate, ItemOut)","from src.schemas import (ItemCreate, ItemUpdate, ItemOut)","Multi-line relative import — fix prefix."),
    _bug(10,"RELATIVE_IMPORT","ImportError","routers/items.py","from .crud import create_item, get_items","from src.crud import create_item, get_items","CRUD helper functions imported relatively."),
    _bug(11,"RELATIVE_IMPORT","ImportError","services.py","from .models import Category\nfrom .schemas import CategoryBase","from src.models import Category\nfrom src.schemas import CategoryBase","Service layer relative import."),
    _bug(12,"RELATIVE_IMPORT","ImportError","dependencies.py","from .models import User\nfrom .database import get_db","from src.models import User\nfrom src.database import get_db","FastAPI dependencies file with relative imports."),
    _bug(13,"RELATIVE_IMPORT","ImportError","routers/admin.py","from ..models import User, Role\nfrom ..auth import require_admin","from src.models import User, Role\nfrom src.auth import require_admin","Double-dot relative imports — replace with absolute."),
    _bug(14,"RELATIVE_IMPORT","ImportError","tasks.py","from .models import Task\nfrom .database import AsyncSession","from src.models import Task\nfrom src.database import AsyncSession","Background task file using relative imports."),
    _bug(15,"RELATIVE_IMPORT","ImportError","routers/crud.py","from .models import *","from src.models import *","Star import with relative prefix."),
    # MISSING_AWAIT (10)
    _bug(16,"MISSING_AWAIT","TypeError: object SQLAlchemy... is a coroutine","routers/crud.py","result = db.execute(select(User))","result = await db.execute(select(User))","AsyncSession.execute() is a coroutine — must be awaited."),
    _bug(17,"MISSING_AWAIT","TypeError: coroutine was never awaited","routers/crud.py","db.commit()","await db.commit()","commit() on AsyncSession must be awaited."),
    _bug(18,"MISSING_AWAIT","TypeError: coroutine","routers/crud.py","db.refresh(obj)","await db.refresh(obj)","refresh() is async on AsyncSession."),
    _bug(19,"MISSING_AWAIT","TypeError: coroutine","routers/crud.py","result = db.scalar(select(User).where(User.id==id))","result = await db.scalar(select(User).where(User.id==id))","scalar() must be awaited on async session."),
    _bug(20,"MISSING_AWAIT","TypeError: coroutine","seed.py","db.execute(text('DELETE FROM users'))","await db.execute(text('DELETE FROM users'))","Async db.execute() in seed script must be awaited."),
    _bug(21,"MISSING_AWAIT","TypeError","routers/crud.py","rows = db.scalars(select(Product)).all()","rows = (await db.scalars(select(Product))).all()","scalars() is async — await before calling .all()."),
    _bug(22,"MISSING_AWAIT","TypeError: coroutine","routers/crud.py","db.delete(obj)\ndb.commit()","await db.delete(obj)\nawait db.commit()","Both delete() and commit() need await on AsyncSession."),
    _bug(23,"MISSING_AWAIT","TypeError: coroutine","routers/crud.py","db.add(new_user)\ndb.commit()\ndb.refresh(new_user)","db.add(new_user)\nawait db.commit()\nawait db.refresh(new_user)","add() is sync but commit() and refresh() are async."),
    _bug(24,"MISSING_AWAIT","TypeError","routers/crud.py","result = db.execute(update(Order).where(Order.id==id).values(status='paid'))","result = await db.execute(update(Order).where(Order.id==id).values(status='paid'))","UPDATE statement execute() must be awaited."),
    _bug(25,"MISSING_AWAIT","RuntimeError: coroutine never awaited","routers/crud.py","count = db.scalar(select(func.count()).select_from(User))","count = await db.scalar(select(func.count()).select_from(User))","Count query scalar() must be awaited."),
    # SEED_UNIQUENESS (10)
    _bug(26,"SEED_UNIQUENESS","sqlalchemy.exc.IntegrityError: UNIQUE constraint failed: users.email","seed.py","for i in range(20):\n    db.add(User(email='admin@example.com', name=f'User {i}'))","for i in range(20):\n    db.add(User(email=f'user_{i+1}@example.com', name=f'User {i+1}'))","Every seed row needs a unique email. Use f-string with index."),
    _bug(27,"SEED_UNIQUENESS","IntegrityError: UNIQUE constraint failed: users.username","seed.py","users = [User(username='admin') for _ in range(10)]","users = [User(username=f'user_{i+1}') for i in range(10)]","Username must be unique per row."),
    _bug(28,"SEED_UNIQUENESS","IntegrityError: UNIQUE constraint failed: products.slug","seed.py","products = [Product(slug='product-slug') for i in range(20)]","products = [Product(slug=f'product-{i+1}') for i in range(20)]","Slug must be unique — append index."),
    _bug(29,"SEED_UNIQUENESS","IntegrityError UNIQUE: items.sku","seed.py","items = [Item(sku='ITEM-001', name=f'Item {i}') for i in range(10)]","items = [Item(sku=f'ITEM-{i+1:03d}', name=f'Item {i+1}') for i in range(10)]","SKU must be unique across all seed items."),
    _bug(30,"SEED_UNIQUENESS","IntegrityError: UNIQUE phone","seed.py","contacts = [Contact(phone='+1555000001') for i in range(5)]","contacts = [Contact(phone=f'+155500000{i+1}') for i in range(5)]","Phone numbers must differ per seed record."),
    _bug(31,"SEED_UNIQUENESS","IntegrityError UNIQUE: organizations.slug","seed.py","orgs = [Org(slug='my-org') for _ in range(3)]","orgs = [Org(slug=f'org-{i+1}') for i in range(3)]","Org slug must be unique."),
    _bug(32,"SEED_UNIQUENESS","IntegrityError UNIQUE: api_keys.key_hash","seed.py","keys = [ApiKey(key_hash='abc123') for _ in range(5)]","import secrets\nkeys = [ApiKey(key_hash=secrets.token_hex(32)) for _ in range(5)]","Generate random unique tokens for API key seeds."),
    _bug(33,"SEED_UNIQUENESS","IntegrityError UNIQUE: employees.employee_id","seed.py","emps = [Employee(employee_id='EMP001') for _ in range(10)]","emps = [Employee(employee_id=f'EMP{i+1:03d}') for i in range(10)]","Employee ID must be unique — use formatted index."),
    _bug(34,"SEED_UNIQUENESS","IntegrityError UNIQUE: invoices.number","seed.py","invoices = [Invoice(number='INV-001') for _ in range(5)]","invoices = [Invoice(number=f'INV-{i+1:04d}') for i in range(5)]","Invoice number must be unique per record."),
    _bug(35,"SEED_UNIQUENESS","IntegrityError UNIQUE: domains.domain_name","seed.py","tenants = [Tenant(domain='example.com') for _ in range(3)]","tenants = [Tenant(domain=f'tenant{i+1}.example.com') for i in range(3)]","Each tenant needs a unique subdomain."),
    # MISSING_AUTH (10)
    _bug(36,"MISSING_AUTH","Endpoint accessible without authentication","routers/crud.py","@router.delete('/{id}')\nasync def delete_item(id: int, db: AsyncSession = Depends(get_db)):\n    ...","@router.delete('/{id}')\nasync def delete_item(id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):\n    ...","Delete endpoints must require authentication."),
    _bug(37,"MISSING_AUTH","No auth on PUT endpoint","routers/crud.py","@router.put('/{id}')\nasync def update_item(id: int, body: ItemUpdate, db=Depends(get_db)):","@router.put('/{id}')\nasync def update_item(id: int, body: ItemUpdate, db=Depends(get_db), current_user=Depends(get_current_user)):","Update endpoints need auth dependency."),
    _bug(38,"MISSING_AUTH","POST endpoint missing auth","routers/crud.py","@router.post('/')\nasync def create_item(body: ItemCreate, db=Depends(get_db)):","@router.post('/')\nasync def create_item(body: ItemCreate, db=Depends(get_db), current_user=Depends(get_current_user)):","Create endpoints must be authenticated."),
    _bug(39,"MISSING_AUTH","Admin endpoint unprotected","routers/admin.py","@router.delete('/users/{id}')\nasync def admin_delete_user(id: int, db=Depends(get_db)):","@router.delete('/users/{id}')\nasync def admin_delete_user(id: int, db=Depends(get_db), current_user=Depends(require_admin)):","Admin endpoints need elevated auth check."),
    _bug(40,"MISSING_AUTH","Bulk operation unprotected","routers/crud.py","@router.post('/bulk-delete')\nasync def bulk_delete(ids: list[int], db=Depends(get_db)):","@router.post('/bulk-delete')\nasync def bulk_delete(ids: list[int], db=Depends(get_db), current_user=Depends(get_current_user)):","Bulk destructive operations require auth."),
    # SQLALCHEMY_TYPE (10)
    _bug(41,"SQLALCHEMY_TYPE","sqlalchemy.exc.ArgumentError: Could not determine join condition","models.py","class Product:\n    id: int\n    name: str\n    price: float","class Product(Base):\n    __tablename__ = 'products'\n    id = Column(Integer, primary_key=True)\n    name = Column(String(255), nullable=False)\n    price = Column(Numeric(10, 2), nullable=False)","Use SQLAlchemy Column types not Python type hints for model fields."),
    _bug(42,"SQLALCHEMY_TYPE","ArgumentError: Mapper could not assemble","models.py","class User(Base):\n    id = int\n    email = str\n    is_active = bool","class User(Base):\n    __tablename__ = 'users'\n    id = Column(Integer, primary_key=True)\n    email = Column(String(255), unique=True, nullable=False)\n    is_active = Column(Boolean, default=True)","Class attributes must be Column() instances."),
    _bug(43,"SQLALCHEMY_TYPE","TypeError: expected Column","models.py","class Order(Base):\n    total = float\n    status = str","class Order(Base):\n    __tablename__ = 'orders'\n    total = Column(Numeric(10, 2), nullable=False)\n    status = Column(String(50), default='pending')","Use Numeric for money, String for status fields."),
    _bug(44,"SQLALCHEMY_TYPE","ProgrammingError: column type","models.py","class Event(Base):\n    starts_at = datetime","class Event(Base):\n    __tablename__ = 'events'\n    starts_at = Column(DateTime(timezone=True), nullable=False)","datetime Python type → Column(DateTime(timezone=True))."),
    _bug(45,"SQLALCHEMY_TYPE","TypeError","models.py","class Tag(Base):\n    metadata = dict","class Tag(Base):\n    __tablename__ = 'tags'\n    extra_data = Column(JSON, nullable=True)","dict → Column(JSON). Also avoid 'metadata' as column name — it's reserved by SQLAlchemy."),
    # PYDANTIC_V2 (10)
    _bug(46,"PYDANTIC_V2","PydanticUserError: `validator` is removed in V2","schemas.py","from pydantic import BaseModel, validator\nclass UserCreate(BaseModel):\n    @validator('email')\n    def email_must_be_lowercase(cls, v):\n        return v.lower()","from pydantic import BaseModel, field_validator\nclass UserCreate(BaseModel):\n    @field_validator('email', mode='before')\n    @classmethod\n    def email_must_be_lowercase(cls, v):\n        return v.lower()","Pydantic v2: @validator → @field_validator with mode='before' and @classmethod."),
    _bug(47,"PYDANTIC_V2","PydanticUserError: `orm_mode` is removed","schemas.py","class UserOut(BaseModel):\n    class Config:\n        orm_mode = True","from pydantic import ConfigDict\nclass UserOut(BaseModel):\n    model_config = ConfigDict(from_attributes=True)","Pydantic v2: Config.orm_mode → model_config = ConfigDict(from_attributes=True)."),
    _bug(48,"PYDANTIC_V2","ValidationError: BaseModel.schema() removed","schemas.py","schema = UserCreate.schema()","schema = UserCreate.model_json_schema()","Pydantic v2: .schema() → .model_json_schema()."),
    _bug(49,"PYDANTIC_V2","TypeError: BaseModel.dict() removed","routers/crud.py","data = user.dict()","data = user.model_dump()","Pydantic v2: .dict() → .model_dump()."),
    _bug(50,"PYDANTIC_V2","AttributeError: parse_obj","routers/crud.py","user = UserOut.parse_obj(row.__dict__)","user = UserOut.model_validate(row)","Pydantic v2: .parse_obj() → .model_validate()."),
    _bug(51,"PYDANTIC_V2","PydanticUserError: root_validator removed","schemas.py","from pydantic import root_validator\n@root_validator\ndef check_dates(cls, values):\n    return values","from pydantic import model_validator\n@model_validator(mode='after')\ndef check_dates(self):\n    return self","Pydantic v2: root_validator → @model_validator(mode='after')."),
    # CORS_CREDENTIALS (5)
    _bug(52,"CORS_CREDENTIALS","CORS error: Credentials not allowed with wildcard origin","main.py","app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True)","app.add_middleware(CORSMiddleware, allow_origins=['https://yourapp.com'], allow_credentials=True)","Browsers block credentials with allow_origins=['*']. List exact origins."),
    _bug(53,"CORS_CREDENTIALS","Access-Control-Allow-Origin cannot be *","main.py","CORSMiddleware(allow_origins=['*'], allow_credentials=True, allow_methods=['*'])","CORSMiddleware(allow_origins=['https://app.example.com'], allow_credentials=True, allow_methods=['GET','POST','PUT','DELETE'])","Specify exact origins and methods when allow_credentials=True."),
    _bug(54,"CORS_CREDENTIALS","CORS blocked","main.py","allow_origins=['*']\nallow_credentials=True","# If you need wildcard, disable credentials:\nallow_origins=['*']\nallow_credentials=False\n# Or specify origins to keep credentials:\nallow_origins=['https://frontend.example.com']","Choose: wildcard origins OR credentials, not both."),
    # MISSING_COMMIT (5)
    _bug(55,"MISSING_COMMIT","Object not persisted after add()","routers/crud.py","db.add(new_user)\nreturn new_user","db.add(new_user)\nawait db.commit()\nawait db.refresh(new_user)\nreturn new_user","Must commit and refresh to persist and get DB-generated fields."),
    _bug(56,"MISSING_COMMIT","Changes lost after session close","routers/crud.py","obj.status = 'paid'\ndb.add(obj)","obj.status = 'paid'\ndb.add(obj)\nawait db.commit()\nawait db.refresh(obj)","Updates need commit() to be persisted to the database."),
    _bug(57,"MISSING_COMMIT","IntegrityError on next request","routers/crud.py","for item in items:\n    db.add(item)","for item in items:\n    db.add(item)\nawait db.commit()","Bulk adds need a single commit after the loop."),
    # DUPLICATE_ROUTER (5)
    _bug(58,"DUPLICATE_ROUTER","APIRouter already included","main.py","app.include_router(users_router, prefix='/api')\n# ... other code ...\napp.include_router(users_router, prefix='/api')","# Include each router exactly once\napp.include_router(users_router, prefix='/api')","Duplicate include_router causes duplicate routes and potential middleware issues."),
    _bug(59,"DUPLICATE_ROUTER","Duplicate routes registered","main.py","app.include_router(items_router)\napp.include_router(items_router)","app.include_router(items_router)","Search for all app.include_router() calls and ensure each router appears once."),
    _bug(60,"DUPLICATE_ROUTER","422 on second call only","main.py","routers = [users_router, items_router, users_router]\nfor r in routers:\n    app.include_router(r)","routers = [users_router, items_router]  # no duplicates\nfor r in routers:\n    app.include_router(r)","Deduplicate the routers list before iterating."),
]

_bugs_file = {"domain": "cross_domain", "version": "1.0", "generated_at": NOW, "examples": _bug_examples}

# ── Write all files ────────────────────────────────────────────────────────────

print("Writing golden examples...")
_file("ecommerce", _ecommerce)
_file("healthcare", _healthcare)
_file("fintech", _fintech)
_file("saas", _saas)
_file("ai_integrated", _ai_integrated)
_file("marketplace", _marketplace)
_file("erp", _erp)
_file("government", _government)
_file("traditional_erp", _traditional_erp)

(OUT / "sqlalchemy_models.json").write_text(json.dumps(_sqla, indent=2))
print(f"  sqlalchemy_models.json: {len(_sqla['examples'])} examples")

(OUT / "bug_fixes.json").write_text(json.dumps(_bugs_file, indent=2))
print(f"  bug_fixes.json: {len(_bug_examples)} examples")

total = sum(len(d) for d in [_ecommerce,_healthcare,_fintech,_saas,_ai_integrated,_marketplace,_erp,_government,_traditional_erp]) + len(_sqla["examples"]) + len(_bug_examples)
print(f"\nDone. Total examples: {total}")
