from typing import Any, Dict, List, Optional  # noqa: D100

import olca_schema as o
from langchain_core.tools import tool
from langgraph.types import interrupt
from olca_ipc import Client


def get_olca_client() -> Client:
    """Get OpenLCA IPC client instance."""
    try:
        return Client("http://localhost:8080")  # Default OpenLCA IPC port
    except Exception:
        # Return None for error handling
        return None

@tool("explore_available_products", return_direct=False)
def explore_available_products(
    product_description: str, 
    limit: int = 20,
) -> Dict[str, Any]:
    """Find available product processes that can be used to model a specific product.

    Args:
        product_description: User's description of the product they want to model (e.g., "concrete", "steel beam", "electric vehicle")
        limit: Maximum number of processes or product systems to return

    Returns:
        Dictionary with available processes or product systems, their providers, and modeling suggestions
    """
    client = get_olca_client()
    if not client:
        return {
            "status": "error",
            "message": "OpenLCA client not available",
        }

    try:
        # Search for flows matching the product description
        flows = client.search(product_description)

        # Separate results by type
        processes = []
        product_systems = []
        
        for flow in flows:
            # Check if ref_type exists and has value attribute
            if (flow.ref_type is not None and 
                hasattr(flow.ref_type, 'value') and 
                flow.ref_type.value == "Process" and 
                flow.flow_type == o.FlowType.PRODUCT_FLOW):
                processes.append(flow)
            elif (flow.ref_type is not None and 
                  hasattr(flow.ref_type, 'value') and 
                  flow.ref_type.value == "ProductSystem"):
                product_systems.append(flow)

        # Group by product name for deduplication
        grouped_results = {}
        
        # Process ProductSystems first (higher priority)
        for product_system in product_systems:
            product_name = product_system.name
            if product_name not in grouped_results:
                grouped_results[product_name] = {
                    "type": "ProductSystem",
                    "id": product_system.id,
                    "name": product_name,
                    "underlying_process_id": _extract_underlying_process_id(product_system.id)  # Placeholder - will be extracted later
                }
        
        # Process Processes (lower priority, only if no ProductSystem exists)
        for process_flow in processes:
            process = client.get(o.Process, process_flow.id)
            if not process:
                continue
                
            # Find quantitative reference flow
            quantitative_ref_exchange_flow = None
            for exchange in process.exchanges:
                if exchange.is_quantitative_reference and not exchange.is_input:
                    quantitative_ref_exchange_flow = exchange.flow
                    break
            
            if not quantitative_ref_exchange_flow:
                continue  # Skip processes without quantitative reference
                
            product_name = quantitative_ref_exchange_flow.name
            
            # Only add if no ProductSystem exists for this product
            if product_name not in grouped_results:
                grouped_results[product_name] = {
                    "type": "Process",
                    "id": process.id,
                    "name": product_name,
                    "process_name": process.name,
                    "flow_id": quantitative_ref_exchange_flow.id,
                    "flow_name": quantitative_ref_exchange_flow.name,
                    "documentation": _extract_essential_documentation(process.process_documentation),
                    "location": process.location.name if process.location else "Unknown",
                }

        # Convert to list and limit results
        available_flows = list(grouped_results.values())[:limit]

        return {
            "status": "success",
            "product_description": product_description,
            "total_flows_found": len(available_flows),
            "available_flows": available_flows,
            "deduplication_applied": True,
            "note": "ProductSystems prioritized over Processes to avoid duplicates"
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to explore product flows for '{product_description}'",
            "details": str(e),
            "suggestion": "Try a more specific product description or check database connection",
        }

@tool("create_product_system_foundation", return_direct=False)
def create_product_system_foundation(
    product_name: str,
    output_amount: float = 1.0,
    output_unit: Optional[str] = None,
    process_name: Optional[str] = None,
    location: Optional[str] = None,
) -> Dict[str, Any]:
    """Create the foundation for a new product system: output product, process, quantitative reference exchange and product system.
    
    This is an atomic operation - if any step fails, all created entities are rolled back.
    
    Args:
        product_name: Name of the output product to create
        output_amount: Amount of the output product (default: 1.0)
        output_unit: Unit for the output product (uses flow's reference unit if None)
        process_name: Name of the process (auto-generated if None)
        location: Location for the process (optional)
    
    Returns:
        Dictionary with foundation creation status and approval request
    """
    client = get_olca_client()
    if not client:
        return {
            "status": "error",
            "message": "OpenLCA client not available",
        }

    # Generate process name if not provided
    if not process_name:
        process_name = f"{product_name} production"

    try:
        # Step 1: Get flow property (default to Mass)
        flow_property = client.get(o.FlowProperty, name="Mass")
        if not flow_property:
            return {
                "status": "error",
                "message": "Flow property 'Mass' not found in database",
            }
        
        # Step 2: Create output product flow
        output_product = o.new_product(product_name, flow_property)
        if output_unit:
            # Get the unit if specified
            unit = client.get(o.Unit, name=output_unit)
            if unit:
                output_product.flow_properties[0].unit = o.as_ref(unit)
        
        # Step 3: Create process
        process = o.new_process(process_name)
        if location:
            process.location = o.as_ref(o.Location(name=location))
        
        # Step 4: Add output product as quantitative reference exchange
        o.new_output(process, output_product, output_amount)
        # The exchange is automatically added to the process, so we need to set the
        # quantitative reference flag on the exchange in the process's exchanges list
        if process.exchanges:
            for exchange in process.exchanges:
                if exchange.flow.id == output_product.id and not exchange.is_input:
                    exchange.is_quantitative_reference = True
                    break
        
        # Create summary for approval
        foundation_summary = {
            "product_name": product_name,
            "output_amount": output_amount,
            "output_unit": output_unit or "reference unit",
            "process_name": process_name,
            "location": location or "unspecified",
        }
        
        # Use interrupt for human approval
        approval_data = {
            "entity_type": "product_system_foundation",
            "entity_summary": f"Product System Foundation: {product_name} ({output_amount} {output_unit or 'units'})",
            "entity_details": {
                "foundation_summary": foundation_summary,
                "will_create": [
                    f"Product flow: {product_name}",
                    f"Process: {process_name}",
                    f"Output exchange: {product_name} ({output_amount} {output_unit or 'units'}) - Quantitative Reference"
                ]
            },
            "action": "create",
            "impact": "Will create the complete foundation for a product system",
            "entity_data": {
                "output_product": output_product,
                "process": process,
                "foundation_summary": foundation_summary,
            }
        }
        
        # Use interrupt for human approval
        user_decision = interrupt(approval_data)
        
        # Process the user's decision
        if user_decision.get("decision") == "approve":
            created_entities = []
            try:
                # Step 1: Save output product
                created_output_product = client.put(output_product)
                if not created_output_product:
                    raise Exception("Failed to create output product in database")
                created_entities.append(("output_product", created_output_product.id))
                
                # Step 2: Save process
                created_process = client.put(process)
                if not created_process:
                    raise Exception("Failed to create process in database")
                created_entities.append(("process", created_process.id))

                # Step 3: Create product system
                config = o.LinkingConfig(
                    prefer_unit_processes=True,
                    provider_linking=o.ProviderLinking.PREFER_DEFAULTS
                )
                created_product_system = client.create_product_system(created_process, config)
                if not created_product_system:
                    raise Exception("Failed to create product system in database")
                created_entities.append(("product_system", created_product_system.id))
                
                return {
                    "status": "success",
                    "message": f"Successfully created product system foundation for '{product_name}'",
                    "product_name": product_name,
                    "process_id": created_process.id,
                    "process_name": process_name,
                    "product_system_id": created_product_system.id,
                    "output_flow_id": created_output_product.id,
                    "output_amount": output_amount,
                    "output_unit": output_unit,
                }
                
            except Exception as e:
                # Rollback: Try to delete created entities
                rollback_errors = []
                for entity_type, entity_id in created_entities:
                    try:
                        if entity_type == "output_product":
                            client.delete(o.Flow(id=entity_id))
                        elif entity_type == "process":
                            client.delete(o.Process(id=entity_id))
                        elif entity_type == "product_system":
                            client.delete(o.ProductSystem(id=entity_id))
                    except Exception as rollback_error:
                        rollback_errors.append(f"Failed to delete {entity_type} {entity_id}: {str(rollback_error)}")
                
                error_message = f"Failed to create product system foundation: {str(e)}"
                if rollback_errors:
                    error_message += f" Rollback errors: {'; '.join(rollback_errors)}"
                
                return {
                    "status": "error",
                    "message": "Failed to create product system foundation",
                    "details": error_message,
                }
        else:
            return {
                "status": "rejected",
                "message": f"Creation of product system foundation for '{product_name}' was rejected",
                "reason": user_decision.get("reason", "No reason provided")
            }

    except Exception as e:
        # Only catch non-interrupt exceptions
        if "Interrupt" in str(e):
            # Re-raise interrupt exceptions to let LangGraph handle them
            raise
        return {
            "status": "error",
            "message": "Failed to create product system foundation",
            "details": str(e),
        }

@tool("create_product_system", return_direct=False)
def create_product_system(
    process_id: str,
    prefer_unit_processes: bool = True,
    product_system_name: str = None,
) -> Dict[str, Any]:
    """Create a product system with human approval.
    
    Args:
        process_id: the process id that we want to link directly to the product system
        prefer_unit_processes: boolean indicating whether to prefer unit processes over system processes
        product_system_name: the name that we will call the product system (optional, will use process name if not provided)
    
    Returns:
        Dictionary with product system status and approval request
    """
    client = get_olca_client()
    if not client:
        return {
            "status": "error",
            "message": "OpenLCA client not available",
        }

    try:
        # Get process from process_id
        process = client.get(o.Process, uid=process_id)
        if not process:
            return {
                "status": "error",
                "message": f"Process with ID '{process_id}' not found",
            }
        
        # Use process name if product_system_name not provided
        if not product_system_name:
            product_system_name = f"{process.name} - Product System"
        
        # Create linking configuration
        config = o.LinkingConfig(
            prefer_unit_processes=prefer_unit_processes,
            provider_linking=o.ProviderLinking.PREFER_DEFAULTS,
        )

        # Use interrupt for human approval
        approval_data = {
            "entity_type": "product_system",
            "entity_summary": f"Product System: {product_system_name} (based on process: {process.name})",
            "entity_details": {
                "name": product_system_name,
                "process_type": "product_system",
                "base_process": process.name,
                "base_process_id": process.id,
                "prefer_unit_processes": prefer_unit_processes,
            },
            "action": "create",
            "impact": "Will create a new product system in the database",
            "entity_data": {
                "process": process,
                "config": config,
                "product_system_name": product_system_name,
            }
        }
        
        user_decision = interrupt(approval_data)
        
        # Process the user's decision
        if user_decision.get("decision") == "approve":
            # Create the product system in the database using the IPC method
            created_product_system_ref = client.create_product_system(process, config)
            if not created_product_system_ref:
                return {
                    "status": "error",
                    "message": f"Failed to create product system '{product_system_name}'",
                }
            
            return {
                "status": "success",
                "message": f"Product system '{product_system_name}' created successfully",
                "product_system_id": created_product_system_ref.id,
                "product_system_name": product_system_name,
                "base_process_id": process.id,
                "base_process_name": process.name,
            }
        else:
            return {
                "status": "rejected",
                "message": f"Creation of product system '{product_system_name}' was rejected",
                "reason": user_decision.get("reason", "No reason provided")
            }

    except Exception as e:
        # Only catch non-interrupt exceptions
        if "Interrupt" in str(e):
            # Re-raise interrupt exceptions to let LangGraph handle them
            raise
        return {
            "status": "error",
            "message": f"Failed to create product system '{product_system_name}'",
            "details": str(e),
        }


@tool("search_exchanges_for_process", return_direct=False)
def search_exchanges_for_process(
    process_id: str,
    material_description: str,
    limit: int = 10,
) -> Dict[str, Any]:
    """Search for flows to add to a process based on natural language description.
    
    This tool uses NLP/LLM to extract materials and amounts from user descriptions,
    then searches the database for matching flows with quantitative reference exchanges.
    Supports iterative refinement based on user feedback and approved exchanges.
    
    **CRITICAL**: This tool can handle MULTIPLE materials in a single call. When users
    request multiple materials (e.g., "0.05kg plastic and 0.2kg glass"), process them
    ALL together in ONE tool call - do not split into separate calls.
    
    When selected_exchanges is provided, the tool will add the selected exchanges directly
    to the process instead of returning search results.
    
    Args:
        process_id: ID of the process to add exchanges to
        material_description: Natural language description of materials/inputs 
                            (e.g., "0.5kg of hot rolled steel input and 1kwh of electricity")
                            Supports multiple materials: "0.05kg plastic and 0.2kg glass"
        feedback: Optional user feedback for refining the search (e.g., "Change steel to 1kg, need European steel")
        approved_exchanges: List of exchanges already approved by user for context
        selected_exchanges: List of selected flows to add directly to the process (if provided, skips search)
        limit: Maximum number of flows to return per material
    
    Returns:
        Dictionary with found flows organized by material in hierarchical structure,
        or exchange addition status if selected_exchanges is provided
    """
    client = get_olca_client()
    if not client:
        return {
            "status": "error",
            "message": "OpenLCA client not available",
        }

    try:
        # Validate process_id format and find process
        process = None
        
        # Check if process_id is a valid UUID format
        if _is_valid_uuid(process_id):
            # It's a valid UUID, try to get process directly
            process = client.get(o.Process, process_id)
        else:
            # It's not a UUID, might be a process name - search for it
            processes = client.search(process_id)
            matching_processes = [
                p for p in processes 
                if hasattr(p, 'name') and p.name == process_id and hasattr(p, 'ref_type') and p.ref_type.value == "Process"
            ]
            
            if matching_processes:
                # Get the full process object
                process = client.get(o.Process, matching_processes[0].id)
            else:
                return {
                    "status": "error",
                    "message": f"Process with ID/name '{process_id}' not found",
                    "suggestion": "Please provide a valid process UUID or exact process name",
                }
        
        if not process:
            return {
                "status": "error",
                "message": f"Process with ID '{process_id}' not found",
                "suggestion": "Please provide a valid process UUID or exact process name",
            }

        extracted_materials = _extract_materials_with_llm(material_description)
        
        if not extracted_materials:
            return {
                "status": "error",
                "message": "Could not extract materials from description",
            }

        # Search for flows for each extracted material
        search_results = {}
        all_flows = []
     
        for material in extracted_materials:
            material_name = material["material"]
            amount = material["amount"]
            unit = material["unit"]
            material_type = material["type"]
            
            # Search for flows using keywords
            search_keywords = _generate_search_keywords(material_name)
            found_flows = []
            
            for keyword in search_keywords:
                flows = client.search(keyword)
                product_flows = [
                    flow for flow in flows 
                    if flow.flow_type == o.FlowType.PRODUCT_FLOW and flow.ref_type.value == "Process"
                ]
                
                # Get detailed flow information with quantitative reference
                for product_flow in product_flows[:limit]:
                    process_detail = client.get(o.Process, product_flow.id)
                    if not process_detail:
                        continue
                        
                    # Find quantitative reference exchange flow
                    quantitative_ref_flow = None
                    for exchange in process_detail.exchanges:
                        if exchange.is_quantitative_reference and not exchange.is_input:
                            quantitative_ref_flow = exchange.flow
                            break
                    
                    if not quantitative_ref_flow:
                        continue
                    
                    # Convert amount to flow's reference unit
                    converted_amount = _convert_to_reference_unit(amount, unit, quantitative_ref_flow)
                    
                    flow_info = {
                        "flow_id": quantitative_ref_flow.id,
                        "process_id": process_detail.id,
                        "flow_name": quantitative_ref_flow.name,
                        "process_name": process_detail.name,
                        "location": process_detail.location.name if process_detail.location else "Unknown",
                        "original_amount": amount,
                        "original_unit": unit,
                        "converted_amount": converted_amount["amount"],
                        "converted_unit": converted_amount["unit"],
                        "material_type": material_type,
                        "search_keyword": keyword,
                        "documentation": _extract_essential_documentation(process_detail.process_documentation),
                        # Required keys for exchange creation
                        "flow": quantitative_ref_flow,  # Full flow object needed for exchange creation
                        "amount": converted_amount["amount"],  # Use converted amount for exchange
                        "is_input": material_type == "input",  # Convert material_type to boolean
                        "is_quantitative_reference": False,  # Default to False, can be overridden
                        "description": f"{converted_amount['amount']} {converted_amount['unit']} of {quantitative_ref_flow.name}",  # Descriptive text
                        "default_provider_process_id": process_detail.id,  # Set to the process that produces this flow
                    }
                    
                    # Avoid duplicates
                    if not any(f["flow_id"] == flow_info["flow_id"] for f in found_flows):
                        found_flows.append(flow_info)
                
                if found_flows:
                    break  # Stop searching if we found flows with this keyword
            
            search_results[material_name] = {
                "original_description": f"{amount} {unit} of {material_name}",
                "material_type": material_type,
                "flows": found_flows[:limit]
            }
            all_flows.extend(found_flows[:limit])

        if not all_flows:
            return {
                "status": "no_results",
                "message": "No matching flows found for the described materials",
                "search_results": search_results,
            }

        # Format search results to match frontend expectations
        formatted_search_results = {}
        for material_name, material_data in search_results.items():
            formatted_search_results[material_name] = {
                "original_description": material_data["original_description"],
                "material_type": material_data["material_type"],
                "flows": material_data["flows"]
            }
        
        approval_data = {
            "status": "search_complete",
            "message": f"Found {len(all_flows)} steel-related flows for process '{process.name}'",
            "search_results": formatted_search_results,
            "total_flows_found": len(all_flows),
            "process_id": process_id,
            "process_name": process.name,
            "is_final_search": True,
            "next_action": "awaiting_approval",
            "entity_data": {
                "process": process,
                "exchanges": all_flows,
            }
        }
        
        # Interrupt for human approval
        user_decision = interrupt(approval_data)

        # Process the user's decision
        if user_decision.get("decision") == "approve":
            try:
                # Get selected exchanges from user decision, or use all flows if none specified
                selected_exchanges = user_decision.get("selected_exchanges", all_flows)
                if not selected_exchanges:
                    selected_exchanges = all_flows
                
                # Get the current process state once
                process_to_add = client.get(o.Process, process_id)
                if not process_to_add:
                    return {
                        "status": "error",
                        "message": f"Process with ID {process_id} not found",
                    }
                
                # Initialize exchanges list if needed
                if not process_to_add.exchanges:
                    process_to_add.exchanges = []
                
                # Track exchanges added and prevent duplicates within the batch
                exchanges_added = 0
                duplicates_skipped = 0
                
                for exchange_data in selected_exchanges:
                    # Check for duplicates against database
                    duplicate_check = _check_exchange_exists(client, process_id, exchange_data)
                    if duplicate_check["exists"]:
                        duplicates_skipped += 1
                        continue
                    
                    # Check for duplicates within the current batch (against process exchanges)
                    is_duplicate_in_batch = False
                    if process_to_add.exchanges:
                        for existing_exchange in process_to_add.exchanges:
                            if (_exchange_matches(existing_exchange, exchange_data)):
                                is_duplicate_in_batch = True
                                break
                    
                    if is_duplicate_in_batch:
                        duplicates_skipped += 1
                        continue
                    
                    # Ensure flow object exists - fetch from database if only flow_id is provided
                    if "flow" not in exchange_data or exchange_data["flow"] is None:
                        if "flow_id" in exchange_data:
                            flow = client.get(o.Flow, exchange_data["flow_id"])
                            if not flow:
                                continue  # Skip this exchange if flow not found
                            exchange_data["flow"] = o.as_ref(flow)
                        else:
                            continue  # Skip this exchange if no flow or flow_id
                    
                    # Create exchange
                    if exchange_data["is_input"]:
                        exchange = o.new_input(
                            process=process_to_add,
                            flow=exchange_data["flow"],
                            amount=exchange_data["amount"]
                        )
                    else:
                        exchange = o.new_output(
                            process=process_to_add,
                            flow=exchange_data["flow"],
                            amount=exchange_data["amount"]
                        )
                    
                    # Set quantitative reference if specified
                    if exchange_data["is_quantitative_reference"]:
                        exchange.is_quantitative_reference = True
                    
                    # Set description
                    if exchange_data["description"]:
                        exchange.description = exchange_data["description"]
                    
                    # Set default provider for inputs
                    if exchange_data["is_input"] and exchange_data["default_provider_process_id"]:
                        provider_process = client.get(o.Process, exchange_data["default_provider_process_id"])
                        if provider_process:
                            exchange.default_provider = o.as_ref(provider_process)
                    
                    # Exchange is automatically added to process by o.new_input()/o.new_output()
                    # No need to manually add it to exchanges_to_add
                    exchanges_added += 1
                
                # Save the process once with all exchanges
                client.put(process_to_add)
                
                return {
                    "status": "success",
                    "message": f"Successfully added {exchanges_added} exchanges to process '{process.name}'" + 
                                (f" (skipped {duplicates_skipped} duplicates)" if duplicates_skipped > 0 else ""),
                    "process_id": process_to_add.id,
                    "exchanges_added": exchanges_added,
                    "duplicates_skipped": duplicates_skipped,
                    "total_selected": len(selected_exchanges),
                }
            except Exception as e:
                return {
                    "status": "error",
                    "message": f"Failed to add exchanges to process '{process_to_add.name}'",
                    "details": str(e),
                    "suggestion": "Check process and exchange data",
                }
        else:
            return {
                "status": "rejected",
                "message": f"Addition of {len(all_flows)} exchanges to process '{process_to_add.name}' was rejected",
                "reason": user_decision.get("reason", "No reason provided")
            }

    except Exception as e:
        # Only catch non-interrupt exceptions
        if "Interrupt" in str(e):
            # Re-raise interrupt exceptions to let LangGraph handle them
            raise
        return {
            "status": "error",
            "message": f"Failed to search for exchanges: {str(e)}",
        }

@tool("calculate_product_system_impacts", return_direct=False)
def calculate_product_system_impacts(
    product_system_id: str,
    impact_method_name: str = "IPCC 2021 AR6",
) -> Dict[str, Any]:
    """Calculate environmental impacts for a product system using a specified impact assessment method.
    
    Args:
        product_system_id: UUID of the product system to analyze
        impact_method_name: Name of the impact assessment method (e.g., "IPCC 2021 AR6", "ReCiPe 2016")
    
    Returns:
        Dictionary with impact calculation results or error information
    """
    client = get_olca_client()
    if not client:
        return {
            "status": "error",
            "message": "OpenLCA client not available",
        }

    try:
        # Step 1: Validate product system exists
        product_system = client.get(o.ProductSystem, product_system_id)
        # Step 1.5: Make sure the product system is linked to de
        try:
            client.update_product_system_links(
                system_id=product_system.id,
                provider_linking="PREFER_DEFAULTS",
                preferred_type="UNIT_PROCESS",
                keep_existing=True  # Clear existing links
            )
        except Exception:
            pass
        if not product_system:
            return {
                "status": "error",
                "message": f"Product system with ID '{product_system_id}' not found",
                "details": "The specified product system does not exist in the database",
                "suggestion": "Check the product system ID or create a product system first",
            }
        
        # Step 2: Check if product system has exchanges
        if not product_system.processes or len(product_system.processes) == 0:
            return {
                "status": "error",
                "message": "Product system has no processes",
                "details": "The product system is incomplete and cannot be calculated",
                "suggestion": "Ensure the product system has been properly created with processes",
            }
        
        # Step 3: Get available impact methods
        methods = client.get_descriptors(o.ImpactMethod)
        if not methods:
            return {
                "status": "error",
                "message": "No impact methods available in database",
                "details": "The database does not contain any impact assessment methods",
                "suggestion": "Ensure the database has impact methods imported",
            }
        
        # Step 4: Find impact method using fuzzy matching
        method_result = _find_impact_method(methods, impact_method_name)
        
        if method_result["status"] == "no_match":
            # Use default method (IPCC 2021 AR6)
            default_index = 42  # IPCC 2021 AR6
            if default_index < len(methods):
                selected_method = methods[default_index]
                method_result = {
                    "status": "default_used",
                    "index": default_index,
                    "name": selected_method.name,
                    "message": f"Using default method '{selected_method.name}' since '{impact_method_name}' was not found"
                }
            else:
                return {
                    "status": "error",
                    "message": "Default impact method not available",
                    "details": "IPCC 2021 AR6 method not found in database",
                    "suggestion": "Check available impact methods in the database",
                }
        elif method_result["status"] == "multiple_matches":
            # Return multiple matches for user to choose
            return {
                "status": "multiple_matches",
                "message": method_result["message"],
                "matches": method_result["matches"],
                "suggestion": method_result["suggestion"],
                "product_system_id": product_system_id,
                "product_system_name": product_system.name
            }
        elif method_result["status"] == "error":
            return method_result
        
        # Step 5: Get the selected impact method
        method_index = method_result["index"]
        if method_index >= len(methods):
            return {
                "status": "error",
                "message": f"Invalid impact method index: {method_index}",
                "details": "The method index is out of range",
                "suggestion": "Try a different impact method",
            }
        
        selected_method = methods[method_index]
        
        # Step 6: Set up calculation
        calculation_setup = o.CalculationSetup(
            target=product_system,
            impact_method=selected_method
        )
        
        # Step 7: Execute calculation
        result = client.calculate(calculation_setup)
        result.wait_until_ready()
        
        # Step 8: Get impact results
        impacts = result.get_total_impacts()
        
        # Step 9: Format results
        impact_results = []
        for impact in impacts:
            if impact.impact_category:
                impact_results.append({
                    "category_name": impact.impact_category.name,
                    "amount": impact.amount,
                    "unit": impact.impact_category.ref_unit if impact.impact_category.ref_unit else "unknown"
                })
        
        # Step 10: Dispose of result
        result.dispose()
        
        # Step 11: Return formatted results
        return {
                "status": "success",
                "message": f"Successfully calculated impacts for '{product_system.name}'",
                "product_system_id": product_system_id,
                "product_system_name": product_system.name,
                "impact_method": selected_method.name,
                "impact_method_index": method_index,
                "total_impacts": len(impact_results),
                "impacts": impact_results,
                "calculation_summary": {
                    "method_used": method_result.get("message", ""),
                    "calculation_date": "now",  # Could add actual timestamp
                    "total_categories": len(impact_results)
                },
            }
        
    except Exception as e:
        return {
            "status": "error",
            "message": "Failed to calculate product system impacts",
            "details": str(e),
            "suggestion": "Check product system completeness and database connection",
        }

# Helper functions for the new tools

def _check_exchange_exists(client, process_id: str, exchange_data: Dict[str, Any]) -> Dict[str, Any]:
    """Check if an exchange already exists in the process (both in-memory and database).
    
    Args:
        client: OpenLCA client instance
        process_id: ID of the process to check
        exchange_data: Dictionary containing exchange data with keys: flow_id, amount, is_input, is_quantitative_reference
    
    Returns:
        Dictionary with check results: {"exists": bool, "location": str, "details": dict}
    """
    try:
        # Get the current process from database to ensure we have the latest state
        process = client.get(o.Process, process_id)
        if not process:
            return {
                "exists": False,
                "error": f"Process with ID '{process_id}' not found",
                "location": None
            }
        
        # Create unique identifier for the new exchange
        # Only check flow_id and is_input - same flow can be both input and output,
        # but same flow should not appear twice as input OR twice as output
        # Normalize description to handle None/empty string differences
        new_description = exchange_data.get("description")
        if new_description is None or new_description == "":
            new_description = None
        
        new_id = (
            exchange_data.get("flow_id"),
            exchange_data.get("is_input"),
            new_description
        )
        
        # Check against existing exchanges in the database process
        if process.exchanges:
            for existing_exchange in process.exchanges:
                # Normalize existing description to handle None/empty string differences
                existing_description = existing_exchange.description if hasattr(existing_exchange, 'description') else None
                if existing_description is None or existing_description == "":
                    existing_description = None
                
                existing_id = (
                    existing_exchange.flow.id if hasattr(existing_exchange, 'flow') and existing_exchange.flow else None,
                    existing_exchange.is_input if hasattr(existing_exchange, 'is_input') else None,
                    existing_description
                )
                
                if new_id == existing_id:
                    return {
                        "exists": True,
                        "location": "database",
                        "details": {
                            "flow_id": existing_exchange.flow.id if existing_exchange.flow else None,
                            "flow_name": existing_exchange.flow.name if existing_exchange.flow else None,
                            "amount": existing_exchange.amount,
                            "is_input": existing_exchange.is_input,
                            "is_quantitative_reference": existing_exchange.is_quantitative_reference
                        }
                    }
        
        return {
            "exists": False,
            "location": None,
            "details": None
        }
        
    except Exception as e:
        return {
            "exists": False,
            "error": f"Error checking exchange: {str(e)}",
            "location": None
        }


def _exchange_matches(existing_exchange, exchange_data: Dict[str, Any]) -> bool:
    """Check if an existing exchange matches the exchange data being added.
    
    Args:
        existing_exchange: The existing exchange object
        exchange_data: Dictionary containing exchange data with keys: flow_id, amount, is_input, is_quantitative_reference
    
    Returns:
        True if the exchanges match, False otherwise
    """
    try:
        # Get flow ID from existing exchange
        existing_flow_id = None
        if hasattr(existing_exchange, 'flow') and existing_exchange.flow:
            existing_flow_id = existing_exchange.flow.id
        
        # Get flow ID from exchange data
        new_flow_id = None
        if "flow_id" in exchange_data:
            new_flow_id = exchange_data["flow_id"]
        elif "flow" in exchange_data and exchange_data["flow"]:
            if hasattr(exchange_data["flow"], 'id'):
                new_flow_id = exchange_data["flow"].id
        
        # Compare flow IDs
        if existing_flow_id != new_flow_id:
            return False
        
        # Compare input/output type
        existing_is_input = getattr(existing_exchange, 'is_input', None)
        new_is_input = exchange_data.get("is_input")
        if existing_is_input != new_is_input:
            return False
        
        # Compare descriptions (normalize None/empty string differences)
        existing_description = getattr(existing_exchange, 'description', None)
        new_description = exchange_data.get("description")
        
        # Normalize both descriptions to handle None/empty string differences
        if existing_description is None or existing_description == "":
            existing_description = None
        if new_description is None or new_description == "":
            new_description = None
            
        if existing_description != new_description:
            return False
        
        return True
        
    except Exception:
        # If there's any error in comparison, assume they don't match
        return False


def _extract_underlying_process_id(product_system_id: str) -> str:
    """Extract the underlying process ID from a ProductSystem.

    Args:
        product_system_id: ID of the ProductSystem
    Returns:
        ID of the underlying process, or None if extraction fails.
    """
    try:
        client = get_olca_client()
        if not client:
            return None
            
        product_system = client.get(o.ProductSystem, product_system_id)
        if not product_system or not product_system.ref_process:
            return None
            
        return product_system.ref_process.id
    except Exception:
        return None

def _extract_essential_documentation(process_doc) -> Dict[str, Any]:
    """Extract only essential documentation fields to reduce token usage."""
    if not process_doc:
        return {"summary": "No documentation available"}
    
    essential_fields = {}
    
    # Technology description (most important for user decisions)
    if hasattr(process_doc, 'technology_description') and process_doc.technology_description:
        essential_fields["technology_description"] = process_doc.technology_description[:300] + "..." if len(process_doc.technology_description) > 300 else process_doc.technology_description
    
    # Data set description (important context)
    if hasattr(process_doc, 'data_set_description') and process_doc.data_set_description:
        essential_fields["data_set_description"] = process_doc.data_set_description[:200] + "..." if len(process_doc.data_set_description) > 200 else process_doc.data_set_description
    
    # Intended application (helps user understand scope)
    if hasattr(process_doc, 'intended_application') and process_doc.intended_application:
        essential_fields["intended_application"] = process_doc.intended_application
    
    # Geography description (location context)
    if hasattr(process_doc, 'geography_description') and process_doc.geography_description:
        essential_fields["geography_description"] = process_doc.geography_description
    
    # Time description (temporal context)
    if hasattr(process_doc, 'time_description') and process_doc.time_description:
        essential_fields["time_description"] = process_doc.time_description
    
    # Use advice (practical guidance)
    if hasattr(process_doc, 'use_advice') and process_doc.use_advice:
        essential_fields["use_advice"] = process_doc.use_advice[:200] + "..." if len(process_doc.use_advice) > 200 else process_doc.use_advice
    
    # If no essential fields found, provide a summary
    if not essential_fields:
        essential_fields["summary"] = "Basic process documentation available"
    
    return essential_fields

def _extract_materials_with_llm(description: str) -> List[Dict[str, Any]]:
    """Extract materials, amounts, and units from natural language description using LLM."""
    import json
    import re
    
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI
    
    # Create LLM instance
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.1,
    )
    
    system_prompt = """You are an expert at extracting material information from natural language descriptions.

    Extract materials, amounts, units, and types from the user's description. Return ONLY a valid JSON array with this exact structure:

    [
    {
        "material": "material name",
        "amount": number,
        "unit": "unit abbreviation",
        "type": "input" or "output"
    }
    ]

    Rules:
    - Extract ALL materials mentioned in the description
    - Convert amounts to numbers (e.g., "half" → 0.5)
    - Use standard unit abbreviations (kg, g, kWh, J, m, mm, etc.)
    - Determine type: "input" for materials used in production, "output" for products/results
    - If type is unclear, default to "input"
    - Handle multiple materials separated by "and", commas, or other conjunctions
    - Be precise with amounts and units

    Examples:
    Input: "0.5kg of hot rolled steel input and 1kWh of electricity"
    Output: [{"material": "hot rolled steel", "amount": 0.5, "unit": "kg", "type": "input"}, {"material": "electricity", "amount": 1.0, "unit": "kWh", "type": "input"}]

    Input: "2kg aluminum, 0.5kWh electricity, 0.1kg plastic"
    Output: [{"material": "aluminum", "amount": 2.0, "unit": "kg", "type": "input"}, {"material": "electricity", "amount": 0.5, "unit": "kWh", "type": "input"}, {"material": "plastic", "amount": 0.1, "unit": "kg", "type": "input"}]

    Return ONLY the JSON array, no other text."""

    try:
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=description)
        ])
        
        # Parse JSON response
        materials = json.loads(response.content.strip())
        
        # Validate structure
        if not isinstance(materials, list):
            raise ValueError("Response is not a list")
        
        for material in materials:
            required_keys = ["material", "amount", "unit", "type"]
            if not all(key in material for key in required_keys):
                raise ValueError(f"Missing required keys in material: {material}")
            
            # Validate types
            if not isinstance(material["amount"], int | float):
                raise ValueError(f"Amount must be a number: {material['amount']}")
            if material["type"] not in ["input", "output"]:
                material["type"] = "input"  # Default to input if invalid
        
        return materials
        
    except Exception:
        # Fallback to simple regex extraction
        
        materials = []
        patterns = [
            r'(\d+(?:\.\d+)?)\s*([a-zA-Z]+)\s+of\s+([^,\n]+)',
            r'(\d+(?:\.\d+)?)\s*([a-zA-Z]+)\s+([^,\n]+)',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, description, re.IGNORECASE)
            for match in matches:
                amount = float(match[0])
                unit = match[1].lower()
                material = match[2].strip()
                
                material_type = "input"
                if any(keyword in material.lower() for keyword in ["output", "product", "result"]):
                    material_type = "output"
                
                materials.append({
                    "material": material,
                    "amount": amount,
                    "unit": unit,
                    "type": material_type
                })
        
        return materials


def _generate_search_keywords(material_name: str) -> List[str]:
    """Generate search keywords for a material name."""
    keywords = [material_name]
    
    # Add common variations
    words = material_name.lower().split()
    if len(words) > 1:
        keywords.extend(words)  # Individual words
        keywords.append(" ".join(words[:2]))  # First two words
    
    # Add common synonyms
    synonyms = {
        "steel": ["iron", "metal"],
        "electricity": ["electric", "power", "energy"],
        "concrete": ["cement"],
        "plastic": ["polymer"],
    }
    
    for word in words:
        if word in synonyms:
            keywords.extend(synonyms[word])
    
    return keywords[:5]  # Limit to 5 keywords


def _convert_to_reference_unit(amount: float, unit: str, flow) -> Dict[str, Any]:
    """Convert amount to flow's reference unit using LLM."""
    import json
    
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI
    
    # Get flow's reference unit
    ref_unit = None
    if hasattr(flow, 'flow_properties') and flow.flow_properties:
        ref_unit = flow.flow_properties[0].unit.name if flow.flow_properties[0].unit else None
    elif hasattr(flow, 'id'):
        # If flow is a Ref object, we need to get the full flow object
        client = get_olca_client()
        if client:
            try:
                full_flow = client.get(o.Flow, flow.id)
                if full_flow and hasattr(full_flow, 'flow_properties') and full_flow.flow_properties:
                    ref_unit = full_flow.flow_properties[0].unit.name if full_flow.flow_properties[0].unit else None
            except Exception:
                pass  # Fall back to original amount/unit
    
    if not ref_unit:
        return {"amount": amount, "unit": unit}
    
    # If units are the same, no conversion needed
    if unit.lower() == ref_unit.lower():
        return {"amount": amount, "unit": ref_unit}
    
    # Create LLM instance
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.1,
    )
    
    system_prompt = """You are an expert at unit conversions for LCA (Life Cycle Assessment) data.

    Convert the given amount from the source unit to the target unit. Return ONLY a valid JSON object with this exact structure:

    {
    "amount": converted_number,
    "unit": "target_unit"
    }

    Rules:
    - Convert the amount accurately using standard conversion factors
    - Use the target unit as provided
    - Handle common LCA units: kg, g, mg, t, kWh, J, MJ, GJ, m, mm, cm, L, m³, etc.
    - Be precise with conversion factors
    - If conversion is not possible or units are incompatible, return the original amount and unit
    - Round to reasonable precision (max 6 decimal places)

    Common conversions:
    - Mass: kg ↔ g (×1000), kg ↔ t (÷1000), g ↔ mg (×1000)
    - Energy: kWh ↔ J (×3,600,000), kWh ↔ MJ (×3.6), J ↔ MJ (÷1,000,000)
    - Length: m ↔ mm (×1000), m ↔ cm (×100), cm ↔ mm (×10)
    - Volume: L ↔ m³ (÷1000), L ↔ mL (×1000)

    Return ONLY the JSON object, no other text."""

    try:
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Convert {amount} {unit} to {ref_unit}")
        ])
        
        # Parse JSON response
        result = json.loads(response.content.strip())
        
        # Validate structure
        if not isinstance(result, dict) or "amount" not in result or "unit" not in result:
            raise ValueError("Invalid response structure")
        
        # Validate amount is a number
        if not isinstance(result["amount"], int | float):
            raise ValueError("Amount must be a number")
        
        return result
        
    except Exception:
        # Fallback to simple conversion logic
        conversions = {
            ("kg", "g"): 1000,
            ("g", "kg"): 0.001,
            ("kg", "t"): 0.001,
            ("t", "kg"): 1000,
            ("g", "mg"): 1000,
            ("mg", "g"): 0.001,
            ("kwh", "j"): 3600000,
            ("j", "kwh"): 0.000000278,
            ("kwh", "mj"): 3.6,
            ("mj", "kwh"): 0.277778,
            ("j", "mj"): 0.000001,
            ("mj", "j"): 1000000,
            ("m", "mm"): 1000,
            ("mm", "m"): 0.001,
            ("m", "cm"): 100,
            ("cm", "m"): 0.01,
            ("cm", "mm"): 10,
            ("mm", "cm"): 0.1,
            ("l", "m³"): 0.001,
            ("m³", "l"): 1000,
            ("l", "ml"): 1000,
            ("ml", "l"): 0.001,
        }
        
        unit_lower = unit.lower()
        ref_unit_lower = ref_unit.lower()
        
        if (unit_lower, ref_unit_lower) in conversions:
            converted_amount = amount * conversions[(unit_lower, ref_unit_lower)]
            return {"amount": converted_amount, "unit": ref_unit}
        
        # If no conversion found, return original
        return {"amount": amount, "unit": unit}


def _find_impact_method(methods, user_input: str) -> Dict[str, Any]:
    """Find impact method using fuzzy matching.
    
    Args:
        methods: List of impact method descriptors from client.get_descriptors(o.ImpactMethod)
        user_input: User's input for impact method name
    
    Returns:
        Dictionary with matching results
    """
    if not user_input or not user_input.strip():
        return {
            "status": "error",
            "message": "No impact method specified",
            "suggestion": "Please specify an impact method name"
        }
    
    user_input = user_input.lower().strip()
    matches = []
    
    # Direct substring matches first
    for i, method in enumerate(methods):
        method_name_lower = method.name.lower()
        if user_input in method_name_lower:
            matches.append({
                "index": i,
                "name": method.name,
                "match_type": "substring"
            })
    
    # If no direct matches, try fuzzy matching with common variations
    if not matches:
        # Common variations mapping
        variations = {
            "recip": "recipe",
            "ipcc": "ipcc",
            "traci": "traci",
            "usetox": "usetox",
            "cml": "cml",
            "ef": "ef",
            "aware": "aware",
            "water": "water",
            "scarcity": "scarcity"
        }
        
        # Check for variations
        for i, method in enumerate(methods):
            method_name_lower = method.name.lower()
            for variation, target in variations.items():
                if variation in user_input and target in method_name_lower:
                    matches.append({
                        "index": i,
                        "name": method.name,
                        "match_type": "variation"
                    })
                    break
    
    # If still no matches, try word-based matching
    if not matches:
        user_words = user_input.split()
        for i, method in enumerate(methods):
            method_name_lower = method.name.lower()
            # Check if any user words appear in method name
            if any(word in method_name_lower for word in user_words if len(word) > 2):
                matches.append({
                    "index": i,
                    "name": method.name,
                    "match_type": "word"
                })
    
    # Return results
    if not matches:
        return {
            "status": "no_match",
            "message": f"No impact method found matching '{user_input}'",
            "suggestion": "Try: 'IPCC 2021 AR6', 'ReCiPe 2016', 'TRACI 2.1', or 'USEtox 2'",
            "default_method": "IPCC 2021 AR6"
        }
    elif len(matches) == 1:
        return {
            "status": "single_match",
            "index": matches[0]["index"],
            "name": matches[0]["name"]
        }
    else:
        return {
            "status": "multiple_matches",
            "message": f"Multiple impact methods found matching '{user_input}'",
            "matches": matches,
            "suggestion": "Please specify which method you'd like to use"
        }

def _is_valid_uuid(uuid_string: str) -> bool:
    """Check if a string is a valid UUID format."""
    import re
    
    # UUID pattern: 8-4-4-4-12 hexadecimal digits
    uuid_pattern = r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
    return bool(re.match(uuid_pattern, uuid_string.strip()))

